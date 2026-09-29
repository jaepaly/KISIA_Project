"""저장된 내부 eval 예측과 infer.py의 재추론 결과가 같은지 확인한다.

내부 eval만 사용해 읽기 전용으로 확인하며 test/gold는 열지 않는다.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import unicodedata

import infer
import train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    import torch
    from torch.utils.data import DataLoader
    torch.set_num_threads(4)
    state = json.loads((args.checkpoint_dir / "trainer_state.json").read_text(encoding="utf-8"))["eval"]
    if not state["split"].startswith("persona_holdout:"):
        raise ValueError("Internal persona holdout checkpoint required")
    rows = train.read_jsonl(train.DEFAULT_DATA)
    _, eval_rows, _ = train.split_examples(rows, eval_ratio=float(state["split"].split(":")[1]),
                                           seed=state["seed"], overfit=0)
    detector = infer.SpanDetector(args.checkpoint_dir, device=args.device)
    loader = DataLoader(train.BioDataset(eval_rows), batch_size=16, shuffle=False,
                        collate_fn=train.make_collator(detector.tok))
    sources, windows = {}, defaultdict(list)
    gold, predictions, scores = defaultdict(set), defaultdict(set), defaultdict(list)
    with torch.no_grad():
        for batch in loader:
            indexes = batch.pop("example_index")
            probs = detector.model(**{k: v.to(detector.device) for k, v in batch.items()}).logits.softmax(-1).cpu()
            ids = probs.argmax(-1).tolist()
            for local, index in enumerate(indexes):
                row = eval_rows[index]
                key = (row["post_id"], row["text_id"])
                if unicodedata.normalize("NFC", row["text"]) != row["text"]:
                    raise ValueError("BIO source is not NFC")
                if key in sources and sources[key] != row["text"]:
                    raise ValueError("Conflicting channel text")
                sources[key] = row["text"]
                windows[key].append(row)
                gold[key].update((s["start"], s["end"], s["type"]) for s in row.get("spans", []))
                valid = [-100 if g == -100 else p for g, p in zip(row["labels"], ids[local])]
                for span in train.decode_token_spans(row["offset_mapping"], valid, detector.id2label):
                    predictions[key].add(span)
                    values = [float(probs[local, i, tag]) for i, ((start, end), tag)
                              in enumerate(zip(row["offset_mapping"], valid)) if tag != -100 and start < end
                              and start < span[1] and end > span[0]]
                    scores[(key, span)].append(train.mean_span_score(values))
    expected = train.filter_span_predictions(predictions, scores, 0.7)
    actual = defaultdict(set)
    mismatch, tokenization_mismatch, max_score_diff = [], [], 0.0
    for key, text in sources.items():
        encoded = detector.tok(text, truncation=True, max_length=256, stride=64,
                               return_overflowing_tokens=True, return_offsets_mapping=True)
        saved = windows[key]
        if len(saved) != len(encoded["input_ids"]) or any(
                row["input_ids"] != encoded["input_ids"][i] or
                [list(pair) for pair in row["offset_mapping"]] != [list(pair) for pair in encoded["offset_mapping"][i]]
                for i, row in enumerate(saved)):
            tokenization_mismatch.append(key)
        inferred = detector.predict_channel(text)
        actual[key] = {(s["start"], s["end"], s["type"]) for s in inferred}
        if actual[key] != expected.get(key, set()):
            mismatch.append({"channel": key, "expected": sorted(expected.get(key, set())), "actual": sorted(actual[key])})
        for span in inferred:
            triple = (span["start"], span["end"], span["type"])
            if (key, triple) in scores:
                max_score_diff = max(max_score_diff, abs(span["score"] - train.mean_span_score(scores[(key, triple)])))
    # 골드와 무관하게 실제 모델의 다중 채널·프로필·긴 입력 동작을 간단히 확인한다.
    longest = max(sources.values(), key=len)
    record = {"post_id": "smoke_b01", "texts": {"title": "집 근처", "body": longest,
              "photo_caption:2": "가족 사진", "photo_caption:10": "퇴근길"}}
    raw = detector.predict_raw(record)
    profile = detector.predict_raw({"persona_id": "smoke", "profile_bio": "동네 기록"})
    for output in (raw, profile):
        for candidate in output["candidates"]:
            assert output["texts"][candidate["text_id"]][candidate["start"]:candidate["end"]] == candidate["text"]
    summary = {"checkpoint": str(args.checkpoint_dir), "device": args.device,
               "data_sha256": train.file_sha256(train.DEFAULT_DATA),
               "eval_windows": len(eval_rows), "eval_channels": len(sources),
               "long_channels": sum(len(v) > 1 for v in windows.values()),
               "tokenization_mismatches": tokenization_mismatch, "span_mismatches": mismatch,
               "max_score_absolute_difference": max_score_diff, "score_tolerance": 1e-5,
               "reference_metrics": train.score_span_sets(gold, expected)["overall"],
               "infer_metrics": train.score_span_sets(gold, actual)["overall"],
               "smoke_post_candidates": len(raw["candidates"]),
               "smoke_profile_candidates": len(profile["candidates"]),
               "test_opened": False}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if mismatch or tokenization_mismatch or max_score_diff > 1e-5:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
