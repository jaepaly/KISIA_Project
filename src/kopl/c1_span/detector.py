"""c1_span 실제 탐지 모델(KoELECTRA 등) 추론 모듈.

docs/roles/howto/b-finetune.md §3.2 및 §9 준수.
- 토큰화 및 offset 매핑
- BIO 태그 시퀀스 디코딩 (decode 함수)
- span.schema.json 계약 규격 출력
- CPU 지연 시간 측정 지원
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    ALLOWED_TYPES,
    format_output,
    format_span_id,
    normalize_nfc,
    sort_spans,
)


def decode(
    text: str,
    offsets: List[Tuple[int, int]],
    tags: List[str],
) -> List[Dict[str, Any]]:
    """BIO 태그 시퀀스와 offset 매핑을 문자 단위 스팬으로 역변환합니다.

    docs/roles/howto/b-finetune.md §3.2 참조.
    """
    spans: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None

    for (s, e), tag in zip(offsets, tags):
        if s == e:
            continue
        if tag.startswith("B-"):
            if cur:
                spans.append(cur)
            cur = {"start": s, "end": e, "type": tag[2:]}
        elif tag.startswith("I-") and cur and cur["type"] == tag[2:]:
            cur["end"] = e
        else:
            if cur:
                spans.append(cur)
            cur = None

    if cur:
        spans.append(cur)

    for sp in spans:
        sp["text"] = text[sp["start"]:sp["end"]]

    return spans


class SpanDetector:
    """KoELECTRA 기반 1단 준식별자 탐지기.

    docs/roles/howto/b-finetune.md §9 참조.
    """

    def __init__(
        self,
        model_dir: str,
        device: str = "cpu",
        max_length: int = 256,
        threshold: float = 0.0,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "SpanDetector를 사용하려면 torch와 transformers가 필요합니다. "
                "pip install torch transformers 로 설치해주세요."
            ) from exc

        self.device = device
        self.max_length = max_length
        self.threshold = threshold
        self.version = model_dir.rstrip("/\\").split("/\\")[-1]

        self.tok = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
        self.model = AutoModelForTokenClassification.from_pretrained(model_dir)
        self.model.eval().to(self.device)
        self.id2label = self.model.config.id2label

    def _detect_channel_raw(
        self,
        text: str,
        text_id: str,
    ) -> List[Dict[str, Any]]:
        """단일 텍스트 채널에서 모델 추론 및 스팬 후보 추출."""
        import torch

        norm_text = normalize_nfc(text)
        with torch.no_grad():
            enc = self.tok(
                norm_text,
                truncation=True,
                max_length=self.max_length,
                return_offsets_mapping=True,
                return_tensors="pt",
            )
            raw_offsets = enc.pop("offset_mapping")[0].tolist()
            offsets: List[Tuple[int, int]] = [(int(s), int(e)) for s, e in raw_offsets]

            enc = {k: v.to(self.device) for k, v in enc.items()}
            logits = self.model(**enc).logits[0]
            probs = logits.softmax(dim=-1)
            ids = probs.argmax(dim=-1).tolist()
            conf = probs.max(dim=-1).values.tolist()

            tags = [self.id2label.get(i, "O") for i in ids]
            decoded_spans = decode(norm_text, offsets, tags)

            raw_spans: List[Dict[str, Any]] = []
            for sp in decoded_spans:
                token_confs = [
                    c for (s, e), c in zip(offsets, conf)
                    if s >= sp["start"] and e <= sp["end"]
                ]
                score = round(min(token_confs), 4) if token_confs else 0.5
                if score < self.threshold:
                    continue

                sp_type = sp["type"]
                if sp_type not in ALLOWED_TYPES:
                    continue

                raw_spans.append({
                    "text_id": text_id,
                    "start": sp["start"],
                    "end": sp["end"],
                    "text": sp["text"],
                    "type": sp_type,
                    "level": "implicit",
                    "subject": "self",
                    "score": score,
                })
            return raw_spans

    def detect(
        self,
        text: str,
        post_id: Optional[str] = None,
        text_id: str = "body",
    ) -> Dict[str, Any]:
        """단일 텍스트에서 준식별자 스팬을 탐지하여 span.schema.json 형식으로 반환합니다."""
        pid = post_id or "post_unspecified"
        raw_spans = self._detect_channel_raw(text, text_id=text_id)

        sorted_spans = sort_spans(raw_spans)
        formatted_spans: List[Dict[str, Any]] = []
        for idx, sp in enumerate(sorted_spans, start=1):
            item = dict(sp)
            item["span_id"] = format_span_id(pid, idx, text_id=sp["text_id"])
            formatted_spans.append(item)

        flags = {
            "gen_signal": False,
            "meme_hits": [],
        }

        return format_output(
            post_id=pid,
            model_version=self.version,
            spans=formatted_spans,
            flags=flags,
        )

    def detect_post(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """다중 텍스트 채널(title, body, photo_caption:N, profile_bio)을 포함한 글 전체를 탐지합니다."""
        pid = post.get("post_id") or "post_unspecified"
        all_raw_spans: List[Dict[str, Any]] = []

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

        for tid, txt in channels.items():
            all_raw_spans.extend(self._detect_channel_raw(txt, text_id=tid))

        sorted_spans = sort_spans(all_raw_spans)
        formatted_spans: List[Dict[str, Any]] = []
        for idx, sp in enumerate(sorted_spans, start=1):
            item = dict(sp)
            item["span_id"] = format_span_id(pid, idx, text_id=sp["text_id"])
            formatted_spans.append(item)

        flags = {
            "gen_signal": False,
            "meme_hits": [],
        }

        return format_output(
            post_id=pid,
            model_version=self.version,
            spans=formatted_spans,
            flags=flags,
        )

    def measure_cpu_latency(
        self,
        sample_text: str,
        warmup_runs: int = 5,
        test_runs: int = 50,
        num_threads: int = 4,
    ) -> float:
        """CPU 지연 시간(ms) 중앙값 측정 (docs/roles/B-detector.md §7.1)."""
        import statistics
        import torch

        prev_threads = torch.get_num_threads()
        torch.set_num_threads(num_threads)

        try:
            # 워밍업
            for _ in range(warmup_runs):
                _ = self.detect(sample_text)

            # 실측
            latencies: List[float] = []
            for _ in range(test_runs):
                t0 = time.perf_counter()
                _ = self.detect(sample_text)
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000.0)

            return round(statistics.median(latencies), 2)
        finally:
            torch.set_num_threads(prev_threads)
