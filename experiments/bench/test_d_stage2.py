"""d_stage2 — 가짜 입력 3명으로 사용자 묶기 · test 섞임 차단 · exp09 명령 형식 · 모델 폴백 집계.

    PYTHONIOENCODING=utf-8 PYTHONPATH=src python -m pytest -q --import-mode=importlib experiments/bench/test_d_stage2.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d_stage2  # noqa: E402

TEST_IDS = [f"T01_b{i:03d}" for i in range(255)]


def _span(text: str, body: str, stype: str, level: str = "explicit", subject: str = "self") -> dict:
    start = body.index(text)
    return {"text_id": "body", "start": start, "end": start + len(text), "type": stype,
            "text": text, "level": level, "subject": subject}


@pytest.fixture()
def fake(tmp_path: Path) -> dict:
    bodies = {
        "A01_b01": "저는 마흔여덟 살이고 마포구에 삽니다.",
        "A01_b02": "오늘은 그냥 날씨가 좋았다.",
        "B02_b01": "간호사로 일한 지 십 년째다.",
        "C03_b01": "동생이랑 밥을 먹었다.",
        "C03_b02": "버스에서 졸았다.",
    }
    corpus = {pid: {"post_id": pid, "persona_id": pid.split("_")[0], "texts": {"title": "제목", "body": b}}
              for pid, b in bodies.items()}
    preds = [
        {"post_id": "A01_b01", "spans": [_span("마흔여덟", bodies["A01_b01"], "AGE"),
                                         _span("마포구", bodies["A01_b01"], "LOC_ADMIN")]},
        {"post_id": "A01_b02", "spans": []},
        {"post_id": "B02_b01", "spans": [_span("간호사", bodies["B02_b01"], "JOB")]},
        {"post_id": "C03_b01", "spans": [_span("동생", bodies["C03_b01"], "FAM", "implicit")]},
        {"post_id": "C03_b02", "spans": [_span("버스에서", bodies["C03_b02"], "COMMUTE", "inferential")]},
    ]
    preds_path = tmp_path / "preds.jsonl"
    preds_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in preds), encoding="utf-8")
    splits = tmp_path / "test_post_ids.json"
    splits.write_text(json.dumps({"note": "가짜", "count": 255, "post_ids": TEST_IDS}), encoding="utf-8")
    return {"corpus": corpus, "preds": preds, "preds_path": preds_path, "splits": splits, "out": tmp_path / "out"}


def test_group_users(fake: dict) -> None:
    users = d_stage2.group_users(fake["preds"], fake["corpus"])
    assert [u["persona_id"] for u in users] == ["A01", "B02", "C03"]
    assert [len(u["posts"]) for u in users] == [2, 1, 2]
    assert users[0]["user_ref"].startswith("u_") and len(users[0]["user_ref"]) == 14
    # span_id 는 탐지기와 같은 규칙으로 붙고, 원문 채널이 따라온다
    assert [s["span_id"] for s in users[0]["posts"][0]["spans"]] == ["A01_b01_s01", "A01_b01_s02"]
    assert set(users[0]["posts"][0]["texts"]) == {"title", "body"}


def test_run_rules(fake: dict) -> None:
    res = d_stage2.run_stage2(fake["preds_path"], fake["out"], mode="rules", corpus=fake["corpus"], splits=fake["splits"])
    json.dumps(res)  # 직렬화 가능
    assert res["meta"]["n_users"] == 3 and res["meta"]["n_posts"] == 5
    assert len(res["meta"]["preds_sha256"]) == 64
    rows = [json.loads(l) for l in (fake["out"] / "stage2_preds.jsonl").read_text(encoding="utf-8").splitlines()]
    by = {r["persona_id"]: r["findings"] for r in rows}
    assert by["A01"]["age"]["verdict"] == "specified" and by["A01"]["location"]["verdict"] == "specified"
    assert by["B02"]["occupation"]["verdict"] == "specified" and by["B02"]["age"]["verdict"] == "abstain"
    assert by["C03"]["family"]["verdict"] == "narrowed" and by["C03"]["commute"]["verdict"] == "weak_signal"
    assert all(len(f) == 7 for f in by.values())
    assert res["spans"]["dropped"] == 0
    assert res["fallback_rate"] is None and res["config"]["model_max_spans"] == 16


def test_limit_and_post_ids(fake: dict) -> None:
    res = d_stage2.run_stage2(fake["preds_path"], fake["out"], corpus=fake["corpus"], splits=fake["splits"], limit_users=2)
    assert res["meta"]["n_users"] == 2
    res = d_stage2.run_stage2(fake["preds_path"], fake["out"], corpus=fake["corpus"], splits=fake["splits"],
                              post_ids=["C03_b01"])
    assert res["meta"]["n_users"] == 1 and res["meta"]["n_posts"] == 1


def test_test_posts_blocked(fake: dict) -> None:
    leak = {"post_id": TEST_IDS[0], "spans": []}
    fake["preds_path"].write_text(fake["preds_path"].read_text(encoding="utf-8") + json.dumps(leak) + "\n", encoding="utf-8")
    fake["corpus"][TEST_IDS[0]] = {"post_id": TEST_IDS[0], "persona_id": "T01", "texts": {"body": "글"}}
    with pytest.raises(ValueError, match="test 글 1편"):
        d_stage2.run_stage2(fake["preds_path"], fake["out"], corpus=fake["corpus"], splits=fake["splits"])
    res = d_stage2.run_stage2(fake["preds_path"], fake["out"], corpus=fake["corpus"], splits=fake["splits"], allow_test=True)
    assert res["meta"]["n_test_posts"] == 1


def test_splits_must_be_dict_255(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"post_ids": TEST_IDS[:6]}), encoding="utf-8")
    with pytest.raises(AssertionError):
        d_stage2.load_test_ids(bad)
    real = d_stage2.load_test_ids()  # 저장소 파일 — dict 의 post_ids 255개
    assert len(real) == 255


def test_model_fallback_counted(fake: dict) -> None:
    class Broken:  # 닫는 괄호 없이 끝나는 출력 = 상한에 잘림 → 앱처럼 규칙 폴백
        def generate(self, prompt: str) -> str:
            return '{"findings": {"age": '

    res = d_stage2.run_stage2(fake["preds_path"], fake["out"], mode="model", corpus=fake["corpus"],
                              splits=fake["splits"], model=Broken(), adapter=fake["out"])
    assert res["fallback_rate"] == 1.0 and res["parse_failure_rate"] == 1.0
    assert res["fallback_reasons"]["model output truncated"]["count"] == 3
    assert res["config"]["adapter"] == str(fake["out"]) and res["config"]["adapter_sha256"] is None


@pytest.mark.parametrize("env", [None, "", "C:/ckpt/env_adapter"])
def test_resolve_adapter_matches_app(env: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """앱 infer.py:243 과 같은 식 — 빈 환경변수도 기본값으로 바꾸지 않고 그대로(빈 경로) 쓴다."""
    import os

    if env is None:
        monkeypatch.delenv("STAGE2_ADAPTER_DIR", raising=False)
    else:
        monkeypatch.setenv("STAGE2_ADAPTER_DIR", env)
    app = Path(os.getenv("STAGE2_ADAPTER_DIR", d_stage2.infer._DEFAULT_ADAPTER))  # infer.Stage2Model 의 식
    assert d_stage2.resolve_adapter(None) == app
    if env == "":
        assert d_stage2.resolve_adapter(None) == Path("") != d_stage2.infer._DEFAULT_ADAPTER
    assert d_stage2.resolve_adapter("C:/arg") == Path("C:/arg")  # 인자가 먼저


def test_exp09_commands() -> None:
    gen, score = d_stage2.exp09_commands("v2", "C:/ckpt/adapter_v2")
    assert gen[0] == sys.executable and score[0] == sys.executable
    assert Path(gen[1]).name == "run_config.py" and Path(gen[1]).parent.name == "exp09-external-agreement"
    assert gen[2:] == ["--config", "v2", "--adapter", str(Path("C:/ckpt/adapter_v2"))]
    assert Path(score[1]).name == "score.py"
    assert score[2:] == ["--qwen-file", "qwen_cfg_v2.jsonl", "--out", "metrics_cfg_v2.json"]
    assert d_stage2.exp09_commands("v1")[0][2:] == ["--config", "v1"]
    with pytest.raises(ValueError):
        d_stage2.exp09_commands("v3")


@pytest.mark.parametrize("final", [False, True])
def test_cli_never_runs_exp09(fake: dict, monkeypatch: pytest.MonkeyPatch, final: bool) -> None:
    """단독 CLI 는 --final 이어도 subprocess 를 한 번도 부르지 않는다 (exp09 는 d_downstream --final 에서만)."""
    from unittest import mock

    monkeypatch.setattr(d_stage2, "load_corpus", lambda *a, **k: fake["corpus"])
    monkeypatch.setattr(d_stage2, "SPLITS", fake["splits"])
    monkeypatch.setattr(d_stage2, "_git_commit", lambda: "")  # 지문용 git 호출도 막아 subprocess 0회를 그대로 본다
    with mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen:
        argv = ["--preds", str(fake["preds_path"]), "--out", str(fake["out"]), "--mode", "rules"]
        assert d_stage2.main(argv + (["--final"] if final else [])) == 0
    run.assert_not_called()
    popen.assert_not_called()
    assert not hasattr(d_stage2, "run_exp09")


def test_compare_stage2(fake: dict, tmp_path: Path) -> None:
    """두 실행의 stage2_preds.jsonl 을 user_ref × 속성으로 조인 — 분모는 조인된 사용자 × 7."""
    a = d_stage2.run_stage2(fake["preds_path"], tmp_path / "a", mode="rules", corpus=fake["corpus"], splits=fake["splits"])
    rows = [json.loads(l) for l in (tmp_path / "a" / "stage2_preds.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[0]["findings"]["age"]["verdict"] = "__다름__"  # 한 칸만 바꾼다
    b_path = tmp_path / "b.jsonl"
    b_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[:2]), encoding="utf-8")  # 1명 빠짐
    c = d_stage2.compare_stage2(a["out_file"], b_path)
    assert (c["n_users_a"], c["n_users_b"], c["n_users_joined"], c["only_in_a"]) == (3, 2, 2, 1)
    assert (c["n_pairs"], c["n_agree"]) == (14, 13)
    assert c["verdict_agreement"] == round(13 / 14, 4) and c["per_attr_agreement"]["age"] == 0.5
