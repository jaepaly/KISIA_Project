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
import glob
import json
import re
import statistics as stat
import sys
from pathlib import Path

# Windows 콘솔이 CP949 로 잡혀 있어도 한글이 깨지지 않게
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

HANJA = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF]")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
# 한글 자모 이모티콘. ㅎㅎ ㅋㅋ ㅜㅜ ㅠㅠ 는 이모지 정규식에 안 걸린다.
# 문체 리얼리티의 핵심 지표라 따로 센다 (연속은 1회로 묶는다: "ㅋㅋㅋㅋ" = 1)
JAMO_EMO = re.compile(r"[ㅋㅎㅜㅠㅡㅅ]{1,}")
PUNCT = re.compile(r"[.,!?~…·;:\"'“”‘’()\[\]<>]")

# 문장 분리. 종결부호만으로 자르면 "쉼표로 이어붙이는" 인물의 문장이
# 문단 통째로 한 문장이 되어 평균 길이가 폭주한다(실측 186자).
# 한국어 종결어미 뒤에서도 끊는다.
# 문장 경계 — 줄바꿈은 문장 경계가 아니다. 종결부호와 한국어 종결어미로만 끊는다.
# (\s 가 개행을 포함하므로 종결어미 뒤 줄바꿈에서는 정상적으로 끊긴다)
#
# ⚠️ **말줄임표는 문장 경계가 아니다.** 「..」 「...」 은 문장 안에서 뜸을 들이는 부호로
# 훨씬 자주 쓰인다. 마침표 하나로 보고 끊으면 문장 수가 부풀고 평균 길이가 내려간다 —
# D01(말줄임표 글당 3~4회)에서 문장길이가 −35% 로 잘못 측정됐다.
# 마침표가 둘 이상 이어지면 말줄임표로 보고 끊지 않는다.
#
# ⚠️ 다만 **종결어미 뒤의 말줄임표는 문장 끝이다.** 「나갔다... 커피 샀다...」 는
# 두 문장이다. 종결어미 조건에서 말줄임표를 건너뛰지 않으면 뒤의 \s+ 가 안 맞아
# 한 문장으로 붙고, 과대계수가 과소계수로 뒤집힌다. 말줄임표를 삼켜서 끊는다.
SENT_SPLIT = re.compile(
    r"(?:(?<!\.)\.(?!\.)|[!?]+|"           # 홑마침표만. .. 과 ... 은 뺀다
    r"(?<=[요음함다죠네])[.…]*\s+|"           # 종결어미 (뒤에 말줄임표가 붙어도)
    r"(?<=[요음함다죠네])[.…]{2,})"           # 종결어미 + 말줄임표 (공백 없이 이어져도)
)
LINE_SPLIT = re.compile(r"\n+")
# 해요체/합쇼체 종결 vs 반말·명사형 종결
POLITE_END = re.compile(r"(요|죠|습니다|입니다|세요)\s*$")


def post_metrics(body: str) -> dict:
    sents = [s.strip() for s in SENT_SPLIT.split(body) if s and s.strip()]
    # 3자 미만 조각은 분리 오류로 보고 앞 문장에 붙인다
    merged: list[str] = []
    for x in sents:
        if merged and len(x) < 3:
            merged[-1] += " " + x
        else:
            merged.append(x)
    sents = merged
    lens = [len(s) for s in sents] or [0]
    polite = sum(1 for s in sents if POLITE_END.search(s))
    lines = [x.strip() for x in LINE_SPLIT.split(body) if x.strip()]
    llens = [len(x) for x in lines] or [0]
    eojeol = [len(x.split()) for x in lines] or [0]

    return {
        "글자수": len(body),
        "문장수": len(sents),
        "줄수": len(lines),
        "줄길이_평균": stat.mean(llens),
        "줄당_어절": stat.mean(eojeol),
        "문장길이_평균": stat.mean(lens),
        "문장길이_표준편차": stat.pstdev(lens) if len(lens) > 1 else 0.0,
        "부호": len(PUNCT.findall(body)),
        "한자": len(HANJA.findall(body)),
        "이모지": len(EMOJI.findall(body)),
        "자모이모티콘": len(JAMO_EMO.findall(body)),
        "존댓말_문장": polite,
        "존댓말_비율": polite / len(sents) if sents else 0.0,
    }


def body_of(r: dict) -> str:
    """texts 구조와 옛 형식을 둘 다 읽는다 (p1.0 이전 코퍼스 호환).

    계측은 본문만 본다 — 제목·캡션은 길이가 달라 섞으면 문장길이가 왜곡된다.
    """
    t = r.get("texts")
    if isinstance(t, dict):
        return t.get("body", "")
    return r.get("body", "")


def aggregate(records: list[dict]) -> dict:
    ms = [post_metrics(body_of(r)) for r in records]
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


# voice 자유서술에서 숫자를 뽑는다. 선언값과 실측을 나란히 놓지 않으면
# "통제해서 갈렸다"와 "각자 반대로 빗나가서 갈렸다"가 구분되지 않는다.
DECLARED = {
    "문장길이": ("문장길이_평균", re.compile(r"평균\s*(\d+)\s*자")),
    "이모지":   ("자모이모티콘", re.compile(r"글?당?\s*(\d+)\s*~?\s*(\d+)?\s*회")),
    "오타율":   (None, re.compile(r"글?당?\s*(\d+)\s*~?\s*(\d+)?\s*건")),
    "줄바꿈":   ("줄당_어절", re.compile(r"(\d+)\s*~\s*(\d+)\s*어절")),
}


# 자모 이모티콘을 실제로 쓴다고 적었는지. 「이모지」 축은 부호·이모티콘·자모를
# 통틀어 담아서, 「말줄임표를 글당 3~4회」 같은 값이 들어온다. 그 숫자를 자모이모티콘
# 목표로 읽으면 실측 0 과 대조되어 −100% 오탐이 난다 (D01 사례).
# 낱자 하나도 잡는다 — 「'ㅋ'를 글당 8회」 처럼 쓴다.
# ㅋㅎㅜㅠ 는 완성 음절이 아니라 낱자라 본문에 우연히 섞이지 않는다.
#
# ⚠️ 「이모지」·「이모티콘」 이라는 **낱말은 근거로 쓰지 않는다.** 실측 6명이
# 「그림 이모지는 사용하지 않음」 처럼 부정문으로 그 낱말을 쓰고 있어서,
# 낱말만 보고 통과시키면 그림 이모지 목표치가 자모 목표로 읽혀 −100% 가 그대로 남는다
# (C03·C06·C08·C11·C16·D05). 실제 자모 낱자나 「자모」 라는 말만 근거로 삼는다.
JAMO_DECLARED = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]|자모")


def declared_targets(persona: dict) -> dict:
    """voice 에 적힌 목표 수치를 뽑는다. 못 뽑으면 그 항목은 건너뛴다."""
    out = {}
    voice = persona.get("voice") or {}
    for vkey, (metric, pat) in DECLARED.items():
        if not metric or vkey not in voice:
            continue
        val = str(voice[vkey])
        # 「이모지」 축에 자모 얘기가 없으면 그 숫자는 다른 것(말줄임표·괄호 등)의 빈도다
        if metric == "자모이모티콘" and not JAMO_DECLARED.search(val):
            continue
        m = pat.search(val)
        if not m:
            continue
        nums = [int(g) for g in m.groups() if g]
        out[metric] = sum(nums) / len(nums)
    return out


def compare_declared(measured: dict, targets: dict, carded: set | None = None) -> list[str]:
    """선언값과 실측을 대조한다.

    carded 는 「카드에 근거가 있는 축」이다. 근거 없는 축은 작성자가 정한 값이라,
    벗어났을 때 «모델이 못 따라간 것»인지 «목표가 임의였던 것»인지 구분해야 한다.
    S01 의 문장길이 −39% 가 후자였다.
    """
    if not targets:
        return []
    lines = ["  [선언값 대비]"]
    for metric, target in targets.items():
        v = measured.get(metric)
        if v is None:
            continue
        dev = (v - target) / target * 100 if target else 0
        mark = "OK " if abs(dev) <= 25 else "✗  "
        tag = "" if carded is None or metric in carded else "  ← 카드 근거 없음"
        lines.append(
            f"  {mark}   {metric:16} 선언 {target:g} · 실측 {v:g} ({dev:+.0f}%){tag}")
    return lines


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
    ap.add_argument("--cards", default=None,
                    help="카드 디렉터리. 선언값에 카드 근거가 있는지 표시한다")
    ap.add_argument("--personas", default=None,
                    help="인물 JSON 디렉터리. voice 선언값과 실측을 나란히 본다")
    args = ap.parse_args()

    rubric = json.loads(Path(args.rubric).read_text(encoding="utf-8-sig")) if args.rubric else None
    fail = 0

    # PowerShell 은 와일드카드를 펼치지 않고 그대로 넘긴다. 여기서 직접 처리한다.
    paths: list[str] = []
    for a in args.jsonl:
        hits = sorted(glob.glob(a))
        paths += hits if hits else [a]
    if not paths:
        print("읽을 파일이 없다")
        return 1

    for path in paths:
        if not Path(path).is_file():
            print(f"(없음: {path})")
            continue
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
        # 인물 JSON 이 있으면 선언값 대비를 먼저 보여준다
        pid = recs[0].get("persona_id")
        if args.personas and pid:
            pf = Path(args.personas) / f"{pid}.json"
            if pf.is_file():
                pj = json.loads(pf.read_text(encoding="utf-8-sig"))
                tgt = declared_targets(pj)
                carded = None
                if args.cards:
                    try:
                        from validate import load_card_axes
                        ca = load_card_axes(args.cards)
                        axes = set()
                        for c in pj.get("card_ref", []) or []:
                            axes |= set((ca.get(c) or {}).keys())
                        # voice 키 → 측정 지표 이름으로 환산
                        # 축 이름이 카드·인물 양쪽에서 같아졌다 (§2-⑤-4). 별칭이 필요 없다
                        carded = {DECLARED[k][0] for k in axes if k in DECLARED and DECLARED[k][0]}
                    except Exception:  # noqa: BLE001
                        carded = None
                out = compare_declared(m, tgt, carded)
                if out:
                    print("\n".join(out))
                    fail += sum(1 for l in out if l.strip().startswith("✗"))

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
