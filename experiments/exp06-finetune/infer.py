"""학습된 체크포인트로 글·프로필의 스팬을 찾아 계약 형식으로 반환한다.

로컬 BIO 추론기의 원시 후보는 span.schema.json 계약 출력이 아니다.

21개 라벨 모델은 level/subject를 예측하지 않는다. 계약 출력에는 W2 탐지기의
implicit/self 임시값을 잠정 유지하며, 이는 의미 판정 결과가 아니다.
별도 판정 함수를 전달하면 이 기존 정책을 대체한다. 골드 조회는 하지 않는다.
offset은 NFC로 정규화된 입력 채널을 기준으로 한다.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import unicodedata
import warnings
from typing import Callable

import train
from prepare_bio import LABELS, channel_sort_key


class InferenceError(ValueError):
    pass


def legacy_attributes(texts: dict, candidate: dict) -> dict:
    """호환을 위한 임시값이며 타인 단서도 self로 표시된다."""
    return {"level": "implicit", "subject": "self"}


def input_channels(record: dict) -> tuple[str, str, dict[str, str]]:
    kind = record.get("record_type", "profile" if "profile_bio" in record and "post_id" not in record else "post")
    if kind not in {"post", "profile"}:
        raise InferenceError("record_type must be post or profile")
    identifier = record.get("post_id" if kind == "post" else "persona_id")
    if not isinstance(identifier, str) or not identifier:
        raise InferenceError("A nonempty post_id/persona_id is required")
    if kind == "post":
        channels = record.get("texts")
        if channels is None:
            channels = {key: record[key] for key in ("title", "body") if key in record}
            captions = record.get("photo_captions", [])
            if not isinstance(captions, list):
                raise InferenceError("photo_captions must be a list")
            channels.update({f"photo_caption:{i}": value for i, value in enumerate(captions)
                             if value is not None})
        if not isinstance(channels, dict) or "profile_bio" in channels or "profile_bio" in record:
            raise InferenceError("Post channels must be a mapping; profile_bio must be scanned separately")
        pattern = r"(?:title|body|photo_caption:[0-9]+)"
    else:
        if "post_id" in record:
            raise InferenceError("A profile cannot contain post_id")
        channels = record.get("texts", {"profile_bio": record.get("profile_bio")})
        if not isinstance(channels, dict) or set(channels) != {"profile_bio"}:
            raise InferenceError("A profile must contain only profile_bio")
        pattern = r"profile_bio"
    normalized = {}
    for key, value in channels.items():
        if not isinstance(key, str) or re.fullmatch(pattern, key) is None or not isinstance(value, str):
            raise InferenceError("Invalid text channel or non-string text")
        normalized[key] = unicodedata.normalize("NFC", value)
    return kind, identifier, dict(sorted(normalized.items(), key=lambda pair: channel_sort_key(pair[0])))


class SpanDetector:
    """로컬 체크포인트를 한 번 로드해 여러 레코드에 재사용한다(CPU 기본)."""
    def __init__(self, checkpoint_dir: str | Path, *, device: str = "cpu",
                 min_span_score: float = 0.7, max_length: int = 256, stride: int = 64,
                 batch_size: int = 16, model_version: str | None = None):
        if not 0 <= min_span_score <= 1 or max_length < 8 or not 0 <= stride < max_length - 2 or batch_size < 1:
            raise InferenceError("Invalid threshold/window/batch configuration")
        checkpoint = Path(checkpoint_dir)
        if not checkpoint.is_dir():
            raise InferenceError(f"Local checkpoint missing: {checkpoint}")
        import torch
        from transformers import AutoTokenizer, AutoModelForTokenClassification
        self.torch = torch
        self.device = torch.device(device)
        self.tok = AutoTokenizer.from_pretrained(str(checkpoint), use_fast=True, local_files_only=True)
        if not self.tok.is_fast:
            raise InferenceError("A fast tokenizer is required")
        self.model = AutoModelForTokenClassification.from_pretrained(str(checkpoint), local_files_only=True)
        self.id2label = {int(key): value for key, value in self.model.config.id2label.items()}
        if [self.id2label.get(i) for i in range(len(LABELS))] != LABELS or len(self.id2label) != len(LABELS):
            raise InferenceError("Checkpoint must use the canonical 21-label BIO mapping")
        self.model.eval().to(self.device)
        self.threshold, self.max_length, self.stride, self.batch_size = min_span_score, max_length, stride, batch_size
        self.version = model_version or f"{checkpoint.parent.name}/{checkpoint.name}"

    def predict_channel(self, text: str) -> list[dict]:
        if not text:
            return []
        encoded = self.tok(text, truncation=True, max_length=self.max_length, stride=self.stride,
                           return_overflowing_tokens=True, return_offsets_mapping=True)
        scores = defaultdict(list)
        predictions = set()
        torch = self.torch
        with torch.no_grad():
            for first in range(0, len(encoded["input_ids"]), self.batch_size):
                indexes = range(first, min(first + self.batch_size, len(encoded["input_ids"])))
                features = [{key: encoded[key][i] for key in self.tok.model_input_names if key in encoded}
                            for i in indexes]
                batch = self.tok.pad(features, padding=True, return_tensors="pt")
                probabilities = self.model(**{key: value.to(self.device) for key, value in batch.items()}).logits.softmax(-1).cpu()
                tags = probabilities.argmax(-1).tolist()
                for local, index in enumerate(indexes):
                    offsets = encoded["offset_mapping"][index]
                    ids = [tag if start < end else -100 for (start, end), tag in zip(offsets, tags[local])]
                    spans = train.decode_token_spans(offsets, ids, self.id2label)
                    for span in spans:
                        if not 0 <= span[0] < span[1] <= len(text):
                            raise InferenceError("Tokenizer returned invalid offsets")
                        predictions.add(span)
                        values = [float(probabilities[local, i, tag]) for i, ((start, end), tag)
                                  in enumerate(zip(offsets, ids)) if tag != -100 and start < end
                                  and start < span[1] and end > span[0]]
                        scores[("channel", span)].append(train.mean_span_score(values))
        selected = train.filter_span_predictions({"channel": predictions}, scores, self.threshold)["channel"]
        return [{"start": start, "end": end, "text": text[start:end], "type": type_,
                 "score": train.mean_span_score(scores[("channel", (start, end, type_))])}
                for start, end, type_ in sorted(selected)]

    def predict_raw(self, record: dict) -> dict:
        kind, identifier, texts = input_channels(record)
        candidates = []
        for text_id, text in texts.items():
            for span in self.predict_channel(text):
                span = {**span, "text_id": text_id}
                index = len(candidates) + 1
                span["span_id"] = f"{identifier}_bio_s{index:02d}" if kind == "profile" else f"{identifier}_s{index:02d}"
                candidates.append(span)
        return {"output_kind": "raw_bio_candidates_not_contract", "model_version": self.version,
                "record_type": kind, "post_id" if kind == "post" else "persona_id": identifier,
                "texts": texts, "candidates": candidates,
                "min_span_score": self.threshold,
                "merge_policy": "longest_first_no_overlap_v1",
                "score_policy": "mean_token_probability_then_mean_windows_v1"}

    def detect(self, record: dict, *, resolver: Callable | None = None) -> dict:
        if resolver is None:
            warnings.warn("level=implicit and subject=self are legacy placeholders, not model predictions; "
                          "third-party attribution is NOT resolved.", RuntimeWarning, stacklevel=2)
            resolver = legacy_attributes
        raw = self.predict_raw(record)
        return format_contract(raw, resolver)


def format_contract(raw: dict, resolver: Callable) -> dict:
    """판정 함수는 (texts, candidate_copy)에서 {level, subject}를 반환한다. 대체 라벨은 없다."""
    from kopl.c1_span.schema import validate_span_output
    from jsonschema import Draft202012Validator
    spans = []
    for candidate in raw["candidates"]:
        attributes = resolver(dict(raw["texts"]), dict(candidate))
        if not isinstance(attributes, dict) or set(attributes) != {"level", "subject"}:
            raise InferenceError("Resolver must return exactly level and subject")
        spans.append({**candidate, **attributes})
    key = "post_id" if raw["record_type"] == "post" else "persona_id"
    result = {"schema_version": "1.0", "model_version": raw["model_version"],
              "record_type": raw["record_type"], key: raw[key], "spans": spans}
    schema_path = Path(__file__).resolve().parents[2] / "docs/contracts/span.schema.json"
    Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).validate(result)
    errors = validate_span_output(result, texts=raw["texts"], is_post=raw["record_type"] == "post")
    if errors:
        raise InferenceError("; ".join(errors))
    return result


def detect_spans(post: dict, checkpoint_dir: str, *, resolver: Callable | None = None, **options) -> dict:
    return SpanDetector(checkpoint_dir, **options).detect(post, resolver=resolver)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--post", required=True, help="Input record as JSON")
    parser.add_argument("--raw", action="store_true", help="Return BIO candidates instead of contract output")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--min-span-score", type=float, default=0.7)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--stride", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    detector = SpanDetector(args.checkpoint_dir, device=args.device, min_span_score=args.min_span_score,
                            max_length=args.max_length, stride=args.stride, batch_size=args.batch_size)
    record = json.loads(args.post)
    output = detector.predict_raw(record) if args.raw else detector.detect(record)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
