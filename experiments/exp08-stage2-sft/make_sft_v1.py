"""골드 스팬 + anonymize → v1 SFT 예시 (chat jsonl).

    python experiments/exp08-stage2-sft/make_sft_v1.py [--k 8] [--seed 20260916] [--dev 12]

- 검수 완료 골드 스팬(data/corpus/v0/gold/<pid>_spans.jsonl, reviewed=true)을 사용
- anonymize()로 스팬 본문을 가명 토큰으로 치환해 SFT 입력으로 씀
- 10종 type → 7 attr 매핑 내부 처리
- subject=other 스팬은 evidence 불가 (label-schema §3-1)
- gold 검수자가 이미 함정(통로=) 제거 → 별도 clue_plan 조인 불필요
- test split(#244) 글은 학습에 사용하지 않음
- v0 make_sft.py와 동일 출력 포맷 → train.py 수정 불필요
- --contribution DIR (C 증류 타깃 gold/contribution/<pid>.json) 이 있으면:
    전체-글 예시에만 posts[].contribution(delta) 입력 + assistant 에 recommendation 출력을 붙인다.
    부분집합 예시는 LOO 를 다시 못 구하므로 그대로 둔다 (findings 만).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))
from kopl.c4_stage2.anonymize import anonymize  # noqa: E402
from contribution_targets import load_contribution, post_deltas, recommendation_from_contribution  # noqa: E402

GOLD = ROOT / "data/corpus/v0/gold"
POSTS = ROOT / "data/corpus/v0/posts"
SPLITS = ROOT / "data/corpus/v0/splits"
HERE = Path(__file__).parent

# 10종 type → 7 attr
TYPE_TO_ATTR: dict[str, str] = {
    "AGE": "age",
    "SEX": "sex",
    "LOC_ADMIN": "location",
    "LOC_FACILITY": "location",
    "JOB": "occupation",
    "REL_WORK": "occupation",
    "FAM": "family",
    "REL_HOME": "family",
    "COMMUTE": "commute",
    "INCOME": "income",
}

ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")

CONF = {
    "specified": 0.9,
    "narrowed_implicit": 0.7,
    "narrowed_inferential": 0.6,
    "weak_signal": 0.4,
    "abstain": 0.1,
}

SYSTEM = """공개 게시글 스팬 목록만 보고 글쓴이 7속성(age·sex·location·occupation·family·commute·income)이 얼마나 특정되는지 판정한다.
verdict: specified(확정) · narrowed(범위 좁혀짐) · weak_signal(약한 신호) · abstain(근거 없음 — 추측 금지, 정상 동작).
규칙: evidence 는 근거 스팬의 post_id·span_id 만 (프로필 스팬은 post_id null). subject "other" 는 남의 정보라 근거 불가.
본인 얘기라도 예전 거주지·출신지·방문지·이사 갈 곳·예전 직장은 지금 것이 아니다 — 근거 불가.
cross_post 는 근거가 서로 다른 글 2편 이상일 때만 true. 실제 값(나이·지명)은 쓰지 않는다.
posts[].contribution(이 글을 내렸을 때 위험도 변화, 음수)이 **모든 글에** 주어졌을 때만 recommendation 을 낸다: 기여도 큰 글부터 unpublish 조치를 부담 낮은 순으로, projected_delta 는 그 조치 단독 효과, projected 에 현재→예상 위험도.
contribution 이 없으면 recommendation 을 내지 않는다 — findings 와 rewrites 만.
출력은 {"findings": {7속성 전부}, "rewrites": []} 에 (contribution 이 있을 때) recommendation 을 덧붙인 JSON 하나."""


def user_ref(pid: str) -> str:
    # scripts/seed_sns.py · C gen_contribution_targets.py 와 같은 규칙 (12자리) — 셋이 같아야 조인된다
    return "u_" + hashlib.sha256(pid.encode()).hexdigest()[:12]


def load_test_ids() -> set[str]:
    # 저장소에 고정된 목록(#282)을 읽는다 — gitignore 된 test.jsonl 이 없을 때 빈 집합으로 넘어가 test 가 학습에 섞이지 않게
    path = SPLITS / "test_post_ids.json"
    if not path.exists():
        raise SystemExit(f"고정 test 목록이 없다: {path}")
    ids = json.loads(path.read_text(encoding="utf-8"))["post_ids"]
    if not ids or len(ids) != len(set(ids)):
        raise SystemExit(f"고정 test 목록이 비었거나 중복이 있다: {path}")
    return set(ids)


def load_post_bodies(pid: str) -> dict[str, str]:
    """post_id → body 텍스트"""
    path = POSTS / f"{pid}.jsonl"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        body = d.get("texts", {}).get("body", "")
        if body:
            out[d["post_id"]] = body
    return out


def load_reviewed_spans(pid: str, test_ids: set[str]) -> dict[str, list[dict]]:
    """post_id → reviewed 스팬 리스트 (test 제외). 스팬 없는 글도 빈 리스트로 포함."""
    path = GOLD / f"{pid}_spans.jsonl"
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("reviewed"):
            continue
        pid_post = r["post_id"]
        if pid_post in test_ids:
            continue
        # body 스팬만, offset 완비된 것만
        spans = [
            s for s in (r.get("spans") or [])
            if s.get("text_id") == "body" and s.get("start") is not None and s.get("end") is not None
        ]
        out[pid_post] = spans
    return out


def anonymize_post(body: str, spans: list[dict]) -> tuple[str, dict[str, str], list[dict]]:
    """
    body + gold spans → (가명 본문, key 역매핑, 토큰화된 span 리스트)
    오류 스팬은 조용히 제외.
    """
    valid = []
    for s in spans:
        try:
            extracted = body[s["start"]: s["end"]]
            if extracted != s.get("text", ""):
                continue  # offset 불일치 → 제외
        except Exception:
            continue
        valid.append(s)
    if not valid:
        return body, {}, []
    try:
        anon_body, key = anonymize(body, valid)
    except Exception:
        return body, {}, []
    # 역 매핑: 원문 → 토큰
    rev = {v: tok for tok, v in key.items()}
    # span마다 토큰 텍스트로 교체
    tokenized: list[dict] = []
    for s in valid:
        orig = s.get("text", "")
        token = rev.get(orig, orig)
        tokenized.append({
            "span_id": s["span_id"],
            "text_id": "body",
            "text": token,
            "type": s["type"],
            "level": s["level"],
            "subject": s.get("subject", "self"),
        })
    return anon_body, key, tokenized


def findings_from_spans(post_span_pairs: list[tuple[str, list[dict]]]) -> dict:
    """
    [(post_id, tokenized_spans), ...] → v0 호환 findings dict
    subject=self 스팬만 집계. 함정은 gold 검수 단계에서 제거됨.
    """
    out = {}
    for attr in ATTRS:
        cands: list[tuple[str, str, str]] = []  # (level, post_id, span_id)
        for post_id, spans in post_span_pairs:
            for s in spans:
                if TYPE_TO_ATTR.get(s["type"]) != attr:
                    continue
                if s.get("subject") != "self":
                    continue
                lv = s.get("level")
                if lv not in ("explicit", "implicit", "inferential"):
                    continue
                cands.append((lv, post_id, s["span_id"]))
        evidence = [{"post_id": pid, "span_id": sid} for _, pid, sid in cands]
        posts_seen = {pid for _, pid, _ in cands}
        levels = [lv for lv, _, _ in cands]
        if not cands:
            verdict, conf = "abstain", CONF["abstain"]
        elif "explicit" in levels:
            verdict, conf = "specified", CONF["specified"]
        elif "implicit" in levels:
            verdict, conf = "narrowed", CONF["narrowed_implicit"]
        elif len({pid for lv, pid, _ in cands if lv == "inferential"}) >= 2:
            verdict, conf = "narrowed", CONF["narrowed_inferential"]
        else:
            verdict, conf = "weak_signal", CONF["weak_signal"]
        out[attr] = {
            "verdict": verdict,
            "confidence": conf,
            "cross_post": len(posts_seen) >= 2,
            "evidence": evidence,
        }
    return out


def build_example(
    pid: str, post_entries: list[dict], findings: dict, recommendation: dict | None = None,
) -> dict:
    inp = {
        "user_ref": user_ref(pid),
        "profile": None,
        "posts": post_entries,
    }
    answer: dict = {"findings": findings, "rewrites": []}
    if recommendation is not None:
        answer["recommendation"] = recommendation
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(inp, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
        ]
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=8, help="인물당 부분집합 증강 횟수")
    ap.add_argument("--seed", type=int, default=20260916)
    ap.add_argument("--dev", type=int, default=12, help="dev 로 뗄 인물 수")
    ap.add_argument("--out", default=str(HERE / "data"))
    ap.add_argument("--contribution", default=None,
                    help="C 증류 타깃 디렉터리 (gold/contribution). 있으면 전체-글 예시에 delta 입력 + recommendation 출력")
    a = ap.parse_args()
    contrib_dir = Path(a.contribution) if a.contribution else None
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    test_ids = load_test_ids()

    # 인물 목록 (gold spans 파일 기준)
    pids = sorted(
        p.stem.replace("_spans", "")
        for p in GOLD.glob("[A-E]*_spans.jsonl")
        if not any(x in str(p) for x in ["blind", "iaa", "detect"])
    )
    rng.shuffle(pids)
    dev_pids = set(pids[: a.dev])

    stats = {
        "seed": a.seed,
        "k": a.k,
        "dev_pids": a.dev,
        "test_excluded": len(test_ids),
        "train": 0,
        "dev": 0,
        "personas_with_data": 0,
        "personas_skipped": 0,
        "with_recommendation": 0,
    }

    with (
        (out / "v1_train.jsonl").open("w", encoding="utf-8") as ftr,
        (out / "v1_dev.jsonl").open("w", encoding="utf-8") as fdv,
    ):
        for pid in pids:
            reviewed = load_reviewed_spans(pid, test_ids)
            if not reviewed:
                stats["personas_skipped"] += 1
                continue
            bodies = load_post_bodies(pid)

            # post_id → (tokenized_spans, body)
            post_data: dict[str, tuple[list[dict], str]] = {}
            for post_id, spans in reviewed.items():
                body = bodies.get(post_id, "")
                if not body:
                    continue
                _, _, tokenized = anonymize_post(body, spans)
                post_data[post_id] = (tokenized, body)

            if not post_data:
                stats["personas_skipped"] += 1
                continue

            stats["personas_with_data"] += 1
            sink = fdv if pid in dev_pids else ftr
            key = "dev" if pid in dev_pids else "train"
            post_ids = list(post_data.keys())

            def make_post_entries(pids_subset: list[str]) -> list[dict]:
                return [
                    {"post_id": p, "spans": post_data[p][0]}
                    for p in pids_subset
                ]

            def make_pair_list(pids_subset: list[str]) -> list[tuple[str, list[dict]]]:
                return [(p, post_data[p][0]) for p in pids_subset]

            # 원본 (전체 글) — C 증류 타깃이 있으면 여기에만 delta 입력·recommendation 출력을 붙인다
            entries = make_post_entries(post_ids)
            findings = findings_from_spans(make_pair_list(post_ids))
            recommendation = None
            contrib_path = contrib_dir / f"{pid}.json" if contrib_dir else None
            if contrib_path and contrib_path.exists():
                contrib = load_contribution(contrib_path)
                deltas = post_deltas(contrib)
                if set(deltas) == set(post_ids):      # 초과·부족 모두 거른다 — greedy_path 가 이쪽에 없는 글을 가리킬 수 있다
                    for e in entries:
                        e["contribution"] = deltas[e["post_id"]]
                    recommendation = recommendation_from_contribution(contrib)
                    stats["with_recommendation"] += 1
                else:
                    # C 타깃의 글 집합이 이쪽 (reviewed · test 제외) 과 다르면 붙이지 않는다 — 원인은 로그로
                    print(f"[skip recommendation] {pid}: contribution 글 집합 불일치", file=sys.stderr)
            sink.write(json.dumps(build_example(pid, entries, findings, recommendation), ensure_ascii=False) + "\n")
            stats[key] += 1

            # 부분집합 증강
            if len(post_ids) < 2:
                continue
            seen: set[tuple[str, ...]] = set()
            for _ in range(a.k):
                size = rng.randint(1, len(post_ids) - 1)
                sub = tuple(sorted(rng.sample(post_ids, size)))
                if sub in seen:
                    continue
                seen.add(sub)
                sub_list = list(sub)
                entries = make_post_entries(sub_list)
                findings = findings_from_spans(make_pair_list(sub_list))
                sink.write(json.dumps(build_example(pid, entries, findings), ensure_ascii=False) + "\n")
                stats[key] += 1

    (out / "v1_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(
        f"v1 SFT done - train {stats['train']} / dev {stats['dev']} "
        f"/ personas {stats['personas_with_data']} / skipped {stats['personas_skipped']}"
    )
    print(f"-> {out / 'v1_train.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
