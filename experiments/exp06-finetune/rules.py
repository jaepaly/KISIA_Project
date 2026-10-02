"""W7 명시 AGE·LOC_ADMIN 보강 후보를 찾는다.

규칙은 골드나 test 결과를 받지 않는다. 반환값은 문자 오프셋과 유형이며,
모델 후보와의 무겹침 병합·평가는 별도 단계에서 수행한다.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from kopl.c2_specificity.engine import RegionDictionary
from prepare_bio import channel_sort_key
import train


_TENS = r"(?:스무|스물|서른|마흔|쉰|예순|일흔|여든|아흔)"
_ONES = r"(?:다섯|여섯|일곱|여덟|아홉|하나|둘|셋|넷|한|두|세|네)"
_AGE_ENDING = r"(?:입니다|이에요|이고|인데|이야|이지|이라|임|은|는|이|가|도|만)?"
_AGE_PATTERNS = (
    re.compile(r"(?<![가-힣A-Za-z0-9])(?:[1-9][0-9]?\s*(?:살|세)|[0-9]{2}년생)" + _AGE_ENDING),
    re.compile(r"(?<![가-힣A-Za-z0-9])" + _TENS + r"(?:\s*" + _ONES + r")?(?:\s*(?:살|세))?" + _AGE_ENDING),
    re.compile(r"(?<![가-힣A-Za-z0-9])" + _ONES + r"(?:\s*살|\s+세)" + _AGE_ENDING),
)
_QUANTITY_FOLLOWERS = re.compile(r"\s*(?:번|개|명|분|마리|원|장|그릇|잔)")
_WORD = re.compile(r"[가-힣]+")
_REGION_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "도", "시", "군", "구")
_PARTICLES = tuple(sorted({"으로부터", "에서부터", "에게서는", "에게서", "에서는", "으로", "에서",
                           "부터", "까지", "이라서", "이라고", "이며", "이라", "이고", "에는",
                           "으로는", "로는", "에는", "은", "는", "이", "가", "을", "를",
                           "에", "도", "만", "로", "와", "과", "랑"}, key=len, reverse=True))
# train 검수 골드 331편에서 일반 명사·동사로 쓰여 불일치한 행정구역명/약칭.
# 실제 지명으로도 쓰일 수 있어 v1+규칙 결과의 한계로 기록한다.
TRAIN_AMBIGUOUS_TERMS = frozenset({"동안", "고양", "내면", "동작", "이동", "서면", "경기", "전주"})


def age_spans(text: str) -> set[tuple[int, int, str]]:
    """나이 표현을 찾되 수량 표현과 긴 단어의 일부는 버린다."""
    found: set[tuple[int, int, str]] = set()
    for pattern in _AGE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if end < len(text) and re.match(r"[가-힣A-Za-z0-9]", text[end]):
                continue
            if _QUANTITY_FOLLOWERS.match(text, end):
                continue
            found.add((start, end, "AGE"))
    return found


class ExplicitRules:
    """행정구역 사전을 재사용하며 채널별 명시 단서 후보를 반환한다."""

    def __init__(self, dictionary: RegionDictionary | None = None,
                 excluded_aliases: Iterable[str] = ()) -> None:
        self.dictionary = dictionary or RegionDictionary()
        self.excluded_aliases = TRAIN_AMBIGUOUS_TERMS | frozenset(excluded_aliases)
        self.names: set[str] = set()
        self.aliases: set[str] = set()
        for region in self.dictionary.regions.values():
            names = {region["name"], *region.get("aliases", [])}
            self.names.update(name for name in names if len(name) >= 2 and name not in self.excluded_aliases)
            if region["level"] not in {"sido", "sigungu"}:
                continue
            for name in names:
                for suffix in _REGION_SUFFIXES:
                    if name.endswith(suffix):
                        alias = name[:-len(suffix)]
                        if len(alias) >= 2 and alias not in self.excluded_aliases:
                            self.aliases.add(alias)
                        break

    def location_spans(self, text: str) -> set[tuple[int, int, str]]:
        found: set[tuple[int, int, str]] = set()
        for match in _WORD.finditer(text):
            word = match.group()
            for particle in ("", *_PARTICLES):
                if particle and not word.endswith(particle):
                    continue
                name = word[:-len(particle)] if particle else word
                if name in self.names and self.dictionary.resolve(name):
                    found.add((match.start(), match.end(), "LOC_ADMIN"))
                    break
                if name in self.aliases:
                    found.add((match.start(), match.end(), "LOC_ADMIN"))
                    break
        return found

    def predict_channel(self, text: str) -> set[tuple[int, int, str]]:
        return age_spans(text) | self.location_spans(text)


def merge_with_model(
    post_id: str,
    texts: dict[str, str],
    model_candidates: list[dict],
    detector: ExplicitRules,
) -> tuple[list[dict], dict[str, int]]:
    """모델·규칙 후보를 같은 최장 우선 무겹침 정책으로 채널별 병합한다.

    후보의 출처는 계약 스팬에 넣지 않고 별도 통계로만 반환한다. 규칙 후보에는
    모델 확률이 없으므로 score를 만들어 붙이지 않는다. 원본 모델 후보도 바꾸지 않는다.
    """
    if not isinstance(post_id, str) or not post_id:
        raise ValueError("post_id가 필요합니다.")
    by_channel: dict[str, dict[tuple[int, int, str], dict]] = {tid: {} for tid in texts}
    model_keys: set[tuple[str, int, int, str]] = set()
    for candidate in model_candidates:
        tid, start, end, kind = (candidate[key] for key in ("text_id", "start", "end", "type"))
        if (tid not in texts or not isinstance(start, int) or not isinstance(end, int)
                or not 0 <= start < end <= len(texts[tid])
                or texts[tid][start:end] != candidate.get("text")):
            raise ValueError(f"모델 후보의 채널·문자 경계가 잘못됐습니다: {post_id}/{tid}")
        key = (tid, start, end, kind)
        if key in model_keys:
            raise ValueError(f"모델 후보가 중복됐습니다: {post_id}/{tid}")
        model_keys.add(key)
        span = {"start": start, "end": end, "text": candidate["text"], "type": kind}
        if "score" in candidate:
            span["score"] = candidate["score"]
        by_channel[tid][(start, end, kind)] = span

    rule_keys: set[tuple[str, int, int, str]] = set()
    for tid, text in texts.items():
        for start, end, kind in detector.predict_channel(text):
            if not 0 <= start < end <= len(text):
                raise ValueError(f"규칙 후보의 문자 경계가 잘못됐습니다: {post_id}/{tid}")
            rule_keys.add((tid, start, end, kind))
            by_channel[tid].setdefault((start, end, kind),
                                       {"start": start, "end": end, "text": text[start:end], "type": kind})

    output: list[dict] = []
    selected_keys: set[tuple[str, int, int, str]] = set()
    for tid in sorted(texts, key=channel_sort_key):
        selected = train.resolve_overlapping_spans(by_channel[tid])
        for start, end, kind in sorted(selected):
            selected_keys.add((tid, start, end, kind))
            output.append({**by_channel[tid][(start, end, kind)], "text_id": tid,
                           "span_id": f"{post_id}_s{len(output) + 1:02d}"})
    stats = {
        "model_input": len(model_keys),
        "rule_proposed": len(rule_keys),
        "union_unique": len(model_keys | rule_keys),
        "selected": len(selected_keys),
        "selected_model_only": len(selected_keys & (model_keys - rule_keys)),
        "selected_rule_only": len(selected_keys & (rule_keys - model_keys)),
        "selected_both": len(selected_keys & model_keys & rule_keys),
        "suppressed_by_overlap": len(model_keys | rule_keys) - len(selected_keys),
    }
    return output, stats
