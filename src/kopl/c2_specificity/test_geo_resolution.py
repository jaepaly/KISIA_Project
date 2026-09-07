"""지명 조회 계층 회귀 테스트 (이슈 #115).

인물 32명 중 거주지 조회가 안 되던 13명에서 뽑은 케이스와
기준일 불일치 회귀 케이스를 함께 고정한다. 코드 전체·이름·인구 집계를
정확히 맞혀야 통과한다.

실행:
    python -m kopl.c2_specificity.test_geo_resolution          # 현황 표
    python -m kopl.c2_specificity.test_geo_resolution --strict # 실패가 있으면 종료코드 1

resolve(text, context) 가 생기면 자동으로 그걸 쓴다. 없으면 지금의
specificity(text) 로 대신 재는데, 그건 맥락을 못 받으므로 ① 이 구현되기
전까지는 맥락이 필요한 케이스가 전부 실패로 나온다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kopl.c2_specificity import RegionDictionary

CASES_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "dict" / "admin" / "geo_resolution_cases.json"
)


_FALLBACK: RegionDictionary | None = None


def _resolve(text: str, context: str | None) -> list[str]:
    """조회 계층이 있으면 쓰고, 없으면 지금 사전으로 대신 잰다.

    폴백은 name_index 를 그대로 읽는다. 지금 specificity() 는 코드가 아니라
    인구만 돌려주므로 후보 코드를 비교하려면 사전을 직접 봐야 한다.
    폴백에는 context 를 넘길 자리가 없다 — 그게 구현 ① 이 필요한 이유다.
    """
    global _FALLBACK
    try:                                    # 구현되면 이쪽으로 붙는다
        from kopl.c2_specificity import resolve  # type: ignore[attr-defined]
    except ImportError:
        if _FALLBACK is None:
            _FALLBACK = RegionDictionary()
        return list(_FALLBACK.name_index.get(text.strip(), []))
    return list(resolve(text, context=context) or [])


def run(strict: bool = False) -> int:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    dictionary = RegionDictionary()

    by_cause: dict[str, list[bool]] = {}
    print(f"지명 조회 케이스 {len(cases)}건  (사전 {payload['dict_version']})\n")
    print(f"  {'id':<5} {'원인':<11} {'글의 말':<22} {'판정':<5} 비고")

    for c in cases:
        want = set(c["expect"]["codes"])
        try:
            got = set(_resolve(c["text"], c["context"]))
        except Exception as e:                     # 구현 중 예외도 실패로 센다
            got, err = set(), f"{type(e).__name__}: {e}"
        else:
            err = ""
        expected_names = set(c["expect"]["names"])
        actual_names = {
            str(dictionary.regions[code]["full_name"])
            for code in got
        }
        populations = [
            int(dictionary.regions[code]["population"])
            for code in got
        ]
        result = dictionary.specificity(
            c["text"],
            context=c["context"],
        )
        expected_resolution = (
            "legal_expansion"
            if c["cause"] == "legal_dong" or c["id"] == "R01"
            else "unique"
        )
        expansion_ok = True

        if result.get("resolution") == "legal_expansion":
            expansion_ok = (
                result.get("k_union") == c["expect"]["k_union"]
                and result.get("k_min") == c["expect"]["k_min"]
            )

        # 코드 전체·이름·인구 집계를 모두 고정해 부분집합 통과를 막는다.
        ok = (
            bool(got)
            and got == want
            and actual_names == expected_names
            and sum(populations) == c["expect"]["k_union"]
            and min(populations) == c["expect"]["k_min"]
            and (
                result.get("ambiguous", False)
                is c["expect"]["ambiguous"]
            )
            and result.get("resolution") == expected_resolution
            and expansion_ok
        )
        by_cause.setdefault(c["cause"], []).append(ok)
        note = err or ("" if ok else c["현재_상태"])
        verdict = "OK" if ok else "✗"
        print(
            f"  {c['id']:<5} {c['cause']:<11} "
            f"{c['text']:<22} {verdict:<5} {note}"
        )

    print()
    total = sum(len(v) for v in by_cause.values())
    passed = sum(sum(v) for v in by_cause.values())
    for cause, results in sorted(by_cause.items()):
        print(f"  {cause:<11} {sum(results)}/{len(results)}   {payload['원인'][cause]}")
    print(f"\n  합계 {passed}/{total}")

    if strict and passed < total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run(strict="--strict" in sys.argv))
