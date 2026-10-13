"""exp25 — LOO 기여도를 학습 없이 한 번에: 축별 최고점 닫힌 식 (README D 8번 · 근사기 대체).

    PYTHONIOENCODING=utf-8 PYTHONPATH="src;scripts" python experiments/exp25-contribution-closed-form/closed_form.py

C2 ``risk_total`` 은 7축 각각에서 가장 구체적인 조건 하나의 점수만 골라 같은 가중치로 평균한다.
그래서 글 p 하나를 뺐을 때의 변화는 「축마다 전체 최고점 − p 를 뺀 나머지 최고점」의 평균이다.
글마다 축 점수를 한 번씩만 구하면 모든 글의 delta 가 나온다 — LOO 처럼 위험도를 글 수만큼 다시 계산하지 않는다.

- 입력: 골드 스팬(``gen_contribution_targets.load_spans`` · test 255편 제외) — LOO 정답을 만든 입력과 같다
- 출력: ``predictions/<persona_id>.json`` — exp20 이 읽는 모양(``approximator_targets`` 와 같음)
- 확인: 정답(``data/corpus/v0/gold/contribution``)과 글마다 delta 가 같은지
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for p in (ROOT / "src", ROOT / "scripts"):
    sys.path.insert(0, str(p))

from kopl.c2_specificity import build_conditions  # noqa: E402
from kopl.c2_specificity.engine import risk_by_axis  # noqa: E402
from kopl.c2_specificity.model import AXES, WEIGHTS  # noqa: E402

GOLD = ROOT / "data" / "corpus" / "v0" / "gold"
TARGETS = GOLD / "contribution"
OUT = HERE / "predictions"


def test_post_ids() -> set[str]:
    # 파일은 메타 dict — 목록은 post_ids (dict 를 그대로 set 으로 만들면 키만 남는다)
    ids = set(json.loads((ROOT / "data/corpus/v0/splits/test_post_ids.json").read_text(encoding="utf-8"))["post_ids"])
    if len(ids) != 255:
        raise SystemExit(f"test 글 수가 255 가 아니다: {len(ids)}")
    return ids


def closed_form_deltas(spans_by_post: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, float]:
    """글별 delta = risk(나머지) − risk(전체). 축 점수는 글마다 한 번만 계산한다."""
    by_post = {pid: risk_by_axis(build_conditions(spans, pid)) for pid, spans in spans_by_post.items()}
    weight_sum = sum(WEIGHTS.values())

    def risk(scores: list[dict[str, float]]) -> float:
        return sum(WEIGHTS[a] * max((s[a] for s in scores), default=0.0) for a in AXES) / weight_sum

    baseline = risk(list(by_post.values()))
    out = {}
    for pid in by_post:
        without = risk([s for q, s in by_post.items() if q != pid])
        out[pid] = round(without - baseline, 2)  # 정답 파일과 같은 반올림 (main 의 loo.py)
    return out


def ranked(deltas: Mapping[str, float]) -> list[dict[str, Any]]:
    """계약 순서 — abs(delta) 내림차순 · 동률은 post_id 오름차순."""
    order = sorted(deltas, key=lambda pid: (-abs(deltas[pid]), pid))
    return [{"post_id": pid, "delta": deltas[pid], "rank": i} for i, pid in enumerate(order, 1)]


def main() -> int:
    from gen_contribution_targets import load_spans

    test = test_post_ids()
    OUT.mkdir(exist_ok=True)
    personas = posts = mismatched = 0
    for path in sorted(TARGETS.glob("*.json")):
        persona = path.stem
        gold = {r["post_id"]: r["delta"] for r in json.loads(path.read_text(encoding="utf-8"))["output"]["contributions"]}
        spans = {pid: s for pid, s in load_spans(GOLD, persona).items() if pid not in test}
        if set(spans) != set(gold):
            raise SystemExit(f"{persona}: 글 집합이 정답과 다르다")
        deltas = closed_form_deltas(spans)
        (OUT / f"{persona}.json").write_text(json.dumps(ranked(deltas), ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8", newline="\n")
        personas += 1
        posts += len(deltas)
        for pid, d in deltas.items():
            if abs(d - gold[pid]) > 1e-9:
                mismatched += 1
                print(f"다름 {pid}: 정답 {gold[pid]} · 닫힌 식 {d}")
    print(f"인물 {personas}명 · 글 {posts}편 · 정답과 다른 글 {mismatched}편 → {OUT.relative_to(ROOT)}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
