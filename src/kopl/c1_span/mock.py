"""c1_span 목(Mock) 탐지기 (가짜/테스트용 흉내내기 파일).

docs/roles/howto/e-integration.md §2 및 docs/contracts/span.schema.json 준수.
실제 모델 가중치 없이도 시스템(웹앱) 및 파이프라인 연동 테스트가 동작하도록
간단한 키워드 기반으로 계약 규격의 스팬을 반환합니다.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    ALLOWED_TYPES,
    format_output,
    format_span_id,
    normalize_nfc,
    sort_spans,
)

# 대표 키워드 매핑 (유형 10종 커버)
MOCK_PATTERNS: List[Tuple[str, str, str, str]] = [
    # (패턴/키워드, type, level, subject)
    (r"신갈저수지|서울숲|성수역|호수공원|저수지|호수", "LOC_FACILITY", "inferential", "self"),
    (r"성수동|기흥|동탄|용인|판교|분당|강남", "LOC_ADMIN", "explicit", "self"),
    (r"집\s*근처|집\s*앞|우리\s*동네|동네", "REL_HOME", "inferential", "self"),
    (r"회사\s*앞|사무실\s*근처|공장에서|직장\s*근처", "REL_WORK", "inferential", "self"),
    (r"마흔여덟|서른넷|스물다섯|90년생|80년생|\d{2}대\s*(?:초|중|후)반", "AGE", "explicit", "self"),
    (r"남편|아내|와이프", "SEX", "explicit", "self"),
    (r"생산관리|개발자|엔지니어|카페\s*매니저|공무원", "JOB", "implicit", "self"),
    (r"첫째가|둘째가|손주|아이\s*병원|딸아이|아들", "FAM", "implicit", "self"),
    (r"2호선|분당선|자차\s*출퇴근|퇴근길|출근길|통근", "COMMUTE", "inferential", "self"),
    (r"연봉|성과급|회비|장비\s*값", "INCOME", "inferential", "self"),
]


class MockSpanDetector:
    """계약 준수 목 탐지기."""

    def __init__(self, model_version: str = "mock-c1-0.1.0") -> None:
        self.model_version = model_version
        self._compiled_patterns = [
            (re.compile(pat), typ, lvl, subj)
            for pat, typ, lvl, subj in MOCK_PATTERNS
            if typ in ALLOWED_TYPES
        ]

    def _extract_candidates(self, text: str, text_id: str) -> List[Dict[str, Any]]:
        """단일 텍스트 채널에서 키워드 매칭 및 최장 우선 겹침 방지를 수행합니다."""
        normalized = normalize_nfc(text)
        raw_candidates: List[Dict[str, Any]] = []

        for regex, typ, lvl, subj in self._compiled_patterns:
            for match in regex.finditer(normalized):
                s, e = match.start(), match.end()
                raw_candidates.append({
                    "text_id": text_id,
                    "start": s,
                    "end": e,
                    "text": normalized[s:e],
                    "type": typ,
                    "level": lvl,
                    "subject": subj,
                    "score": 0.85,
                })

        # 겹침 방지: 최장 우선 (Longest match)
        raw_candidates.sort(key=lambda x: (x["end"] - x["start"]), reverse=True)
        accepted: List[Dict[str, Any]] = []
        for cand in raw_candidates:
            c_start, c_end = cand["start"], cand["end"]
            overlap = any(
                not (c_end <= a["start"] or c_start >= a["end"])
                for a in accepted
            )
            if not overlap:
                accepted.append(cand)

        return accepted

    def detect(
        self,
        text: str,
        post_id: Optional[str] = None,
        text_id: str = "body",
    ) -> Dict[str, Any]:
        """단일 텍스트에서 키워드를 찾아 span.schema.json 형식으로 반환합니다."""
        pid = post_id or "post_mock"
        accepted = self._extract_candidates(text, text_id=text_id)

        # 계약 규격 정렬: 텍스트 채널 순서 → start 오름차순
        sorted_candidates = sort_spans(accepted)
        spans: List[Dict[str, Any]] = []
        for idx, item in enumerate(sorted_candidates, start=1):
            spans.append({
                "span_id": format_span_id(pid, idx, text_id=item["text_id"]),
                "text_id": item["text_id"],
                "start": item["start"],
                "end": item["end"],
                "text": item["text"],
                "type": item["type"],
                "level": item["level"],
                "subject": item["subject"],
                "score": item["score"],
            })

        flags = {
            "gen_signal": False,
            "meme_hits": [],
        }

        return format_output(
            post_id=pid,
            model_version=self.model_version,
            spans=spans,
            flags=flags,
        )

    def detect_post(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """다중 텍스트 채널(title, body, photo_caption:N, profile_bio)을 포함한 글 전체를 탐지합니다."""
        pid = post.get("post_id") or "post_mock"
        all_candidates: List[Dict[str, Any]] = []

        # 채널 맵 수집
        channels: Dict[str, str] = {}
        if "texts" in post and isinstance(post["texts"], dict):
            channels.update(post["texts"])
        else:
            if "title" in post and post["title"]:
                channels["title"] = str(post["title"])
            if "body" in post and post["body"]:
                channels["body"] = str(post["body"])
            if "photo_captions" in post and isinstance(post["photo_captions"], list):
                for idx, cap in enumerate(post["photo_captions"]):
                    if cap:
                        channels[f"photo_caption:{idx}"] = str(cap)
            if "profile_bio" in post and post["profile_bio"]:
                channels["profile_bio"] = str(post["profile_bio"])

        # 각 채널별 독립 겹침 방지 탐지
        for tid, txt in channels.items():
            all_candidates.extend(self._extract_candidates(txt, text_id=tid))

        # 전체 스팬을 계약 규격(텍스트 정렬 순서 → start 오름차순)으로 정렬
        sorted_candidates = sort_spans(all_candidates)

        spans: List[Dict[str, Any]] = []
        for idx, item in enumerate(sorted_candidates, start=1):
            spans.append({
                "span_id": format_span_id(pid, idx, text_id=item["text_id"]),
                "text_id": item["text_id"],
                "start": item["start"],
                "end": item["end"],
                "text": item["text"],
                "type": item["type"],
                "level": item["level"],
                "subject": item["subject"],
                "score": item["score"],
            })

        flags = {
            "gen_signal": False,
            "meme_hits": [],
        }

        return format_output(
            post_id=pid,
            model_version=self.model_version,
            spans=spans,
            flags=flags,
        )


_default_mock = MockSpanDetector()


def predict_mock(
    target: Any,
    post_id: Optional[str] = None,
    text_id: str = "body",
) -> Dict[str, Any]:
    """docs/roles/howto/e-integration.md 연동용 간단 호출 함수.

    문자열 또는 post 딕셔너리를 모두 지원합니다.
    """
    if isinstance(target, dict):
        return _default_mock.detect_post(target)
    return _default_mock.detect(str(target), post_id=post_id, text_id=text_id)
