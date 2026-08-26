"""리얼리즘 카드 채점표 → 측정.

이슈 5항: "리얼리즘 카드가 그대로 채점표입니다. 예를 들어 S11이면
문장 30자 내외 / 글 300자 내외 / 반말 회고체 / 부호 전무 / 한자 병기 0~2회 / 노이즈 60%"

이 중 다섯 개는 기계로 잰다. 눈으로 20편을 읽는 것과 별개로, 수치가 있으면
프롬프트를 고친 뒤 나아졌는지를 비교할 수 있다.

    python score.py posts/S01.jsonl --rubric rubrics/S11.json

루브릭 파일이 없으면 측정값만 출력한다 (기준선 잡기용).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as stat
import sys
from pathlib import Path

HANJA = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF]")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
PUNCT = re.compile(r"[.,!?~…·;:\"'“”‘’()\[\]<>]")
SENT_SPLIT = re.compile(r"[.!?…\n]+")
# 해요체/합쇼체 종결 vs 반말·명사형 종결
POLITE_END = re.compile(r"(요|죠|습니다|입니다|세요)\s*$")


def post_metrics(body: str) -> dict:
    sents = [s.strip() for s in SENT_SPLIT.split(body) if s.strip()]
    lens = [len(s) for s in sents] or [0]
    polite = sum(1 for s in sents if POLITE_END.search(s))
    return {
        "글자수": len(body),
        "문장수": len(sents),
        "문장길이_평균": stat.mean(lens),
        "문장길이_표준편차": stat.pstdev(lens) if len(lens) > 1 else 0.0,
        "부호": len(PUNCT.findall(body)),
        "한자": len(HANJA.findall(body)),
        "이모지": len(EMOJI.findall(body)),
        "존댓말_문장": polite,
        "존댓말_비율": polite / len(sents) if sents else 0.0,
    }


def aggregate(records: list[dict]) -> dict:
    ms = [post_metrics(r["body"]) for r in records]
    out = {}
    for k in ms[0]:
        out[k] = round(stat.mean(m[k] for m in ms), 2)
    kinds = [r.get("kind") for r in records]
    out["노이즈_비율"] = round(
        sum(1 for k in kinds if k in ("noise", "ambient")) / len(kinds), 3
    )
    # 문체 획일화 감지: 글마다 문장 길이가 비슷하면 AI 티가 난다
    out["글간_문장길이_편차"] = round(
        stat.pstdev([m["문장길이_평균"] for m in ms]) if len(ms) > 1 else 0.0, 2
    )
    return out


def check(measured: dict, rubric: dict) -> list[str]:
    """루브릭은 {"지표": [최소, 최대]} 또는 {"지표": 목표값} 형태."""
    lines = []
    for key, target in rubric.items():
        if key not in measured:
            lines.append(f"  ?      {key}: 측정 항목에 없음")
            continue
        v = measured[key]
        if isinstance(target, list):
            lo, hi = target
            ok = lo <= v <= hi
            lines.append(f"  {'OK ' if ok else '✗  '}   {key}: {v} (목표 {lo}~{hi})")
        else:
            ok = abs(v - target) <= max(abs(target) * 0.25, 1)
            lines.append(f"  {'OK ' if ok else '✗  '}   {key}: {v} (목표 {target} ±25%)")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", nargs="+")
    ap.add_argument("--rubric", default=None, help="카드 채점표 JSON")
    args = ap.parse_args()

    rubric = json.loads(Path(args.rubric).read_text(encoding="utf-8-sig")) if args.rubric else None
    fail = 0

    for path in args.jsonl:
        recs = [
            json.loads(l) for l in Path(path).read_text(encoding="utf-8-sig").splitlines() if l.strip()
        ]
        if not recs:
            print(f"■ {path} — 비어 있음")
            continue
        m = aggregate(recs)
        print(f"■ {Path(path).name}  {len(recs)}편  "
              f"카드 {','.join(recs[0].get('card_ref', [])) or '-'}  "
              f"모델 {recs[0].get('gen_model', '?')}")
        for k, v in m.items():
            print(f"    {k:20} {v}")
        if rubric:
            print("  [채점]")
            lines = check(m, rubric)
            print("\n".join(lines))
            fail += sum(1 for l in lines if l.strip().startswith("✗"))
        # 리얼리즘 검수 2번 항목: AI는 문장을 고르게 쓴다
        if m["문장길이_표준편차"] < 5:
            print("  ⚠ 문장 길이가 너무 고르다 — 프롬프트에 '들쭉날쭉하게'를 더 구체적으로")
        if m["글간_문장길이_편차"] < 3 and len(recs) > 3:
            print("  ⚠ 글마다 문체가 비슷하다 — voice 파라미터를 강화")
        print()

    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
