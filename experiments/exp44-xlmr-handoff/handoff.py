"""Validate frozen labels, tokenize training only, and evaluate one selected model.

The doctor command uses the standard library. Transformers/torch are loaded only
by prepare/evaluate, or explicitly requested GPU inspection.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import platform
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TYPES = {"AGE", "SEX", "LOC_ADMIN", "LOC_FACILITY", "REL_HOME", "REL_WORK", "JOB", "FAM", "COMMUTE", "INCOME"}
SPAN_FIELDS = {"span_id", "text_id", "start", "end", "text", "type", "level", "subject"}


class ValidationError(ValueError):
    """A frozen artifact or source does not satisfy the handoff contract."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_texts_hash(texts):
    return hashlib.sha256(json.dumps(texts, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def index_unique(rows, label):
    result = {}
    for row in rows:
        pid = row.get("post_id")
        require(isinstance(pid, str) and pid and pid not in result, f"{label}: duplicate/missing post_id {pid!r}")
        result[pid] = row
    return result


def contained(base, relative):
    path = (base / relative).resolve()
    require(not Path(relative).is_absolute() and path.is_relative_to(base.resolve()), f"Unsafe relative path: {relative}")
    return path


def tracked_posts(root=ROOT):
    listing = subprocess.run(["git", "ls-files", "-z", "--", "data/corpus/v0/posts/*.jsonl"],
                             cwd=root, check=True, capture_output=True).stdout
    paths = [p.decode("utf8") for p in listing.split(b"\0") if p]
    require(paths, "No tracked synthetic post sources")
    rows = []
    for path in paths:
        rows.extend(r for r in read_rows(root / path) if "post_id" in r)
    return index_unique(rows, "tracked post sources")


def edge(char):
    return char.isspace() or unicodedata.category(char).startswith("P")


def validate_spans(post_id, texts, spans, strict_boundaries=True):
    warnings = []
    require(isinstance(texts, dict) and texts, f"{post_id}: invalid texts")
    for channel, text in texts.items():
        require(re.fullmatch(r"title|body|photo_caption:\d+", channel) is not None,
                f"{post_id}: invalid post channel {channel}")
        require(isinstance(text, str) and unicodedata.normalize("NFC", text) == text,
                f"{post_id}: source is not NFC")
    require(isinstance(spans, list), f"{post_id}: spans must be a list")
    identities, span_ids = set(), set()
    for s in spans:
        require(isinstance(s, dict) and set(s) == SPAN_FIELDS, f"{post_id}: span must have exactly eight contract fields")
        tid, start, end = s["text_id"], s["start"], s["end"]
        require(tid in texts and type(start) is int and type(end) is int, f"{post_id}: invalid channel/offset")
        text = texts[tid]
        require(0 <= start < end <= len(text) and text[start:end] == s["text"], f"{post_id}: offset mismatch {s}")
        require(unicodedata.normalize("NFC", s["text"]) == s["text"], f"{post_id}: span is not NFC")
        require(s["type"] in TYPES and s["level"] in {"explicit", "implicit", "inferential"}
                and s["subject"] in {"self", "other", "unknown"}, f"{post_id}: invalid span enum")
        require(isinstance(s["span_id"], str) and s["span_id"] and s["span_id"] not in span_ids,
                f"{post_id}: duplicate/missing span_id")
        good_boundary = (not edge(text[start]) and not edge(text[end - 1])
                         and (start == 0 or edge(text[start - 1])) and (end == len(text) or edge(text[end])))
        if not good_boundary:
            require(not strict_boundaries, f"{post_id}: partial eojeol/punctuation boundary {s['text']!r}")
            warnings.append({"post_id": post_id, "span_id": s["span_id"], "reason": "preserved_reference_boundary"})
        identity = tid, start, end, s["type"]
        require(identity not in identities, f"{post_id}: duplicate span")
        identities.add(identity); span_ids.add(s["span_id"])
    for tid in texts:
        ordered = sorted((s for s in spans if s["text_id"] == tid), key=lambda s: s["start"])
        require(all(a["end"] <= b["start"] for a, b in zip(ordered, ordered[1:])), f"{post_id}: overlapping spans")
    return warnings


def validate_split_isolation(split_groups, sources):
    groups = list(split_groups.items())
    for i, (name, ids) in enumerate(groups):
        for other, other_ids in groups[i + 1:]:
            require(not set(ids) & set(other_ids), f"ID leakage: {name}/{other}")
    bodies = {}
    for group, ids in groups:
        for pid in ids:
            body = sources[pid]["texts"].get("body", "")
            if not body.strip():
                continue
            digest = hashlib.sha256(body.encode("utf8")).hexdigest()
            require(digest not in bodies or bodies[digest][0] == group,
                    f"Full-body duplicate across splits: {pid}, {bodies.get(digest)}")
            bodies[digest] = group, pid


def validate_dataset(manifest, sources, base=HERE):
    require(manifest.get("format_version") == 1, "Unsupported manifest version")
    require(manifest.get("model_id") == "FacebookAI/xlm-roberta-large", "Unexpected model ID")
    require(re.fullmatch(r"[0-9a-fA-F]{40}", manifest.get("model_revision", "")) is not None, "Model revision must be a full commit SHA")
    require(manifest.get("threshold") == .7 and manifest.get("seed") == 20260911, "Threshold/seed differs from protocol")
    dev = manifest.get("dev_personas", [])
    require(len(dev) == len(set(dev)) == 9, "Exactly nine frozen dev personas required")
    paths = [manifest["train_labels"]] + [r["labels"] for r in manifest["references"]]
    require(len(paths) == len(set(paths)), "Duplicate label file paths")
    for path, digest in manifest["files_sha256"].items():
        require(sha(contained(base, path)) == digest, f"Frozen file hash mismatch: {path}")
    require(set(paths) <= set(manifest["files_sha256"]), "Every label file must be hash pinned")
    groups = {}; span_counts = {}; all_ids = set(); boundary_warnings = {}
    for relative in paths:
        rows = index_unique(read_rows(contained(base, relative)), relative)
        seen_span_ids = set()
        for pid, row in rows.items():
            require(set(row) == {"post_id", "spans"}, f"{relative}: labels must not contain source texts or metadata")
            require(pid in sources, f"Missing tracked source: {pid}")
            source = sources[pid]
            require(source.get("synthetic") is True, f"Source is not marked synthetic: {pid}")
            require(canonical_texts_hash(source["texts"]) == manifest["source_text_sha256"].get(pid), f"Source text hash mismatch: {pid}")
            warnings = validate_spans(pid, source["texts"], row["spans"], strict_boundaries=relative == manifest["train_labels"])
            boundary_warnings.setdefault(relative, []).extend(warnings)
            for span in row["spans"]:
                require(span["span_id"] not in seen_span_ids, f"{relative}: duplicate span_id across posts")
                seen_span_ids.add(span["span_id"])
        groups[relative] = rows
        all_ids.update(rows)
        span_counts[relative] = sum(len(row["spans"]) for row in rows.values())
    require(set(manifest["source_text_sha256"]) == all_ids, "Source hash IDs differ from frozen label union")
    train = groups[manifest["train_labels"]]
    require(len(train) == 2281 and span_counts[manifest["train_labels"]] == 2706, "Training post/span counts differ from frozen 2281/2706")
    by_size = {}
    names = set()
    for reference in manifest["references"]:
        name, count = reference["name"], reference["posts"]
        require(name not in names, "Duplicate reference name"); names.add(name)
        require(count in {239, 63} and len(groups[reference["labels"]]) == count, f"Reference count mismatch: {name}")
        ids = set(groups[reference["labels"]])
        require(not ids & set(train), f"Train/reference ID leakage: {name}")
        require(count not in by_size or by_size[count] == ids, f"Reference input IDs differ in group {count}")
        by_size[count] = ids
    require(set(by_size) == {239, 63}, "Both original test and fresh validation groups required")
    require(not by_size[239] & by_size[63], "Fresh validation/original test ID leakage")
    split_groups = {"train": set(train), "test": by_size[239], "fresh": by_size[63]}
    validate_split_isolation(split_groups, sources)
    personas = {sources[pid]["persona_id"] for pid in train}
    require(set(dev) <= personas, "Frozen dev persona absent from training pool")
    return groups, {"train_posts": len(train), "train_spans": span_counts[manifest["train_labels"]],
                    "reference_posts": {r["name"]: r["posts"] for r in manifest["references"]},
                    "unique_eval_posts": 302, "dev_personas": dev, "source_hashes_checked": len(all_ids),
                    "id_leakage": 0, "cross_split_full_body_duplicates": 0,
                    "preserved_reference_boundary_warnings": {p: len(w) for p, w in boundary_warnings.items() if w}}


def load_package():
    manifest = read_json(HERE / "manifest.json")
    sources = tracked_posts()
    groups, summary = validate_dataset(manifest, sources)
    return manifest, sources, groups, summary


def load_prepare_module():
    path = ROOT / "experiments/exp06-finetune/prepare_bio.py"
    spec = importlib.util.spec_from_file_location("handoff_shared_prepare", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def require_run_output(path):
    resolved = path.resolve()
    require(resolved.is_relative_to(ROOT.resolve()) and "runs" in resolved.relative_to(ROOT.resolve()).parts,
            "Generated artifacts must stay in a repository runs/ directory")


def prepare(output_dir, offline=False):
    require_run_output(output_dir)
    manifest, sources, groups, _ = load_package()
    require(not output_dir.exists(), f"Output directory already exists: {output_dir}")
    from transformers import AutoTokenizer, __version__ as transformers_version
    tokenizer = AutoTokenizer.from_pretrained(manifest["model_id"], revision=manifest["model_revision"],
                                              use_fast=True, local_files_only=offline)
    require(tokenizer.is_fast, "A fast tokenizer is required")
    shared = load_prepare_module()
    channels = []
    for pid, row in sorted(groups[manifest["train_labels"]].items()):
        source = sources[pid]
        for tid in sorted(source["texts"], key=shared.channel_sort_key):
            channels.append({"post_id": pid, "persona_id": source["persona_id"], "reviewed": True,
                             "text_id": tid, "text": source["texts"][tid],
                             "spans": [s for s in row["spans"] if s["text_id"] == tid]})
    examples, metrics = shared.encode_channels(channels, tokenizer, max_length=256, stride=64)
    require(metrics["roundtrip"]["bad"] == 0 and not metrics["lost_span_ids"], "BIO roundtrip lost/bad spans")
    # Verify shared splitter preserves the predeclared persona holdout before writing.
    import random
    personas = sorted({s["persona_id"] for s in channels})
    random.Random(manifest["seed"]).shuffle(personas)
    require(set(personas[:max(1, round(len(personas) * .1))]) == set(manifest["dev_personas"]), "Frozen dev split differs")
    output_dir.mkdir(parents=True, exist_ok=False)
    shared.write_jsonl(output_dir / "train.jsonl", examples)
    labels = {"labels": shared.LABELS, "label2id": {v: i for i, v in enumerate(shared.LABELS)},
              "id2label": {i: v for i, v in enumerate(shared.LABELS)}}
    dump(output_dir / "labels.json", labels)
    prepared = {"model_id": manifest["model_id"], "model_revision": manifest["model_revision"],
                "source_manifest_sha256": sha(HERE / "manifest.json"),
                "bio_sha256": sha(output_dir / "train.jsonl"), "labels_sha256": sha(output_dir / "labels.json"),
                "train_posts_sha256": hashlib.sha256(json.dumps(sorted(groups[manifest["train_labels"]])).encode()).hexdigest(),
                "files": {name: sha(output_dir / name) for name in ("train.jsonl", "labels.json")},
                "labels": shared.LABELS, "label2id": labels["label2id"],
                "dev_personas": manifest["dev_personas"], "seed": manifest["seed"], "eval_ratio": .1,
                "tokenizer": {"class": type(tokenizer).__name__, "transformers_version": transformers_version,
                              "max_length": 256, "stride": 64, "revision": manifest["model_revision"]},
                "train_posts": 2281, "train_spans": 2706, "roundtrip": metrics["roundtrip"],
                "lost_span_ids": metrics["lost_span_ids"], "metrics": metrics}
    dump(output_dir / "prepare_manifest.json", prepared)
    return prepared


def iou(a, b):
    if a["text_id"] != b["text_id"]:
        return 0.0
    return max(0, min(a["end"], b["end"]) - max(a["start"], b["start"])) / (max(a["end"], b["end"]) - min(a["start"], b["start"]))


def match_counts(gold, predicted, exact=False):
    # Same descending-IoU greedy policy as the repository evaluator.
    pairs = sorted(((iou(a, b), i, j) for i, a in enumerate(gold) for j, b in enumerate(predicted)
                    if a["type"] == b["type"] and iou(a, b) >= (1 if exact else .5)), reverse=True)
    used_g, used_p = set(), set()
    for _, i, j in pairs:
        if i not in used_g and j not in used_p:
            used_g.add(i); used_p.add(j)
    return len(used_g), len(predicted) - len(used_p), len(gold) - len(used_g)


def metrics(counts):
    tp, fp, fn = (sum(c[i] for c in counts) for i in range(3))
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else 0.,
            "recall": tp / (tp + fn) if tp + fn else 0., "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.}


def score_reference(gold, predictions):
    require(set(gold) == set(predictions), "Reference/prediction IDs differ")
    result = {"partial": metrics([match_counts(gold[p]["spans"], predictions[p]) for p in gold]),
              "exact": metrics([match_counts(gold[p]["spans"], predictions[p], True) for p in gold])}
    result["by_type"] = {}
    for typ in sorted(TYPES):
        g = {pid: [s for s in row["spans"] if s["type"] == typ] for pid, row in gold.items()}
        p = {pid: [s for s in predictions[pid] if s["type"] == typ] for pid in gold}
        result["by_type"][typ] = {**metrics([match_counts(g[pid], p[pid]) for pid in gold]),
                                  "support": sum(map(len, g.values())),
                                  "interpretation": "sample_insufficient" if sum(map(len, g.values())) < 30 else "supported"}
    zero = [pid for pid in gold if not gold[pid]["spans"]]
    result["zero_gold"] = {"posts": len(zero), "posts_with_false_spans": sum(bool(predictions[p]) for p in zero),
                           "false_spans": sum(len(predictions[p]) for p in zero)}
    return result


def checkpoint_hashes(directory):
    return {p.relative_to(directory).as_posix(): sha(p) for p in directory.rglob("*") if p.is_file()}


def evaluate(run_dir, device="cpu", threads=4, bio_dir=None):
    require_run_output(run_dir)
    manifest, sources, groups, _ = load_package()
    require(threads >= 1, "threads must be positive")
    selection = read_json(run_dir / "selection.json")
    run_metrics = read_json(run_dir / "run_metrics.json")
    require(run_metrics.get("completed") is True, "Training is not complete")
    if "selection" in run_metrics:
        require(run_metrics["selection"] == selection, "Run metrics/selection mismatch")
    for key in ("model_id", "model_revision", "dev_personas"):
        require(selection.get(key) == manifest[key], f"Selection {key} mismatch")
    require(selection.get("min_span_score") == .7 and selection.get("checkpoint") == "best", "Selection threshold/checkpoint mismatch")
    require(selection.get("source_manifest_sha256") == sha(HERE / "manifest.json"), "Selection source manifest hash mismatch")
    prepared_dir = run_dir.parent / "bio-xlmr"
    # Trainer can store its input directory relative to the run or as a local path.
    if selection.get("prepared_dir"):
        prepared_dir = Path(selection["prepared_dir"])
        if not prepared_dir.is_absolute():
            prepared_dir = run_dir / prepared_dir
    if bio_dir is not None:
        prepared_dir = bio_dir
    prepared = read_json(prepared_dir / "prepare_manifest.json")
    require(selection.get("prepare_manifest_sha256") == sha(prepared_dir / "prepare_manifest.json"), "Selected prepare manifest hash mismatch")
    for key, filename in (("bio_sha256", "train.jsonl"), ("labels_sha256", "labels.json")):
        require(selection.get(key) == prepared.get(key) == sha(prepared_dir / filename), f"Selected {key} mismatch")
    require(prepared["source_manifest_sha256"] == sha(HERE / "manifest.json"), "Prepared package hash mismatch")
    for key in ("model_id", "model_revision", "dev_personas", "seed"):
        require(prepared.get(key) == manifest[key], f"Prepared {key} mismatch")
    require(selection.get("seed") == manifest["seed"], "Selected seed mismatch")
    checkpoint = run_dir / "best"
    require(selection.get("checkpoint_files_sha256") == checkpoint_hashes(checkpoint),
            "Selected checkpoint config/tokenizer/weight file hashes mismatch")
    actual_weights = {p.name: sha(p) for p in checkpoint.iterdir()
                      if p.name.endswith(".safetensors") or (p.name.startswith("pytorch_model") and p.suffix == ".bin")}
    require(actual_weights and selection.get("weights_sha256") == actual_weights, "Selected checkpoint weight hashes mismatch")
    output = run_dir / "evaluation"
    require(not output.exists(), "Evaluation directory exists; refusing repeated inference/overwrite")
    # Reserve before inference, so failures cannot silently cause a second test run.
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "started.json", {"selection_sha256": sha(run_dir / "selection.json"), "threshold": .7})
    sys.path.insert(0, str(ROOT / "src"))
    import torch
    import transformers
    from kopl.c1_span.infer import SpanDetector
    torch.set_num_threads(threads)
    detector = SpanDetector(checkpoint, device=device, min_span_score=.7, max_length=256, stride=64)
    ids = sorted({pid for ref in manifest["references"] for pid in groups[ref["labels"]]})
    predicted, raw = {}, []
    for pid in ids:
        row = detector.predict_raw({"post_id": pid, "texts": sources[pid]["texts"]})
        raw.append(row); predicted[pid] = row["candidates"]
    (output / "predictions.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in raw), encoding="utf8")
    result = {"model_id": manifest["model_id"], "model_revision": manifest["model_revision"],
              "selection_sha256": sha(run_dir / "selection.json"), "threshold": .7, "rules": "off",
              "environment": {"python": platform.python_version(), "torch": str(torch.__version__),
                              "transformers": transformers.__version__, "device": device, "threads": threads,
                              "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
                              "gpu": torch.cuda.get_device_name(0) if device == "cuda" and torch.cuda.is_available() else None,
                              "attention_backend": getattr(detector.model.config, "_attn_implementation", None)},
              "inferred_posts": len(ids), "matching": "type equal; character IoU >= .5; descending IoU greedy 1:1",
              "references": {ref["name"]: score_reference(groups[ref["labels"]],
                             {pid: predicted[pid] for pid in groups[ref["labels"]]}) for ref in manifest["references"]}}
    baseline_path = manifest.get("baseline_metrics")
    if baseline_path:
        require(baseline_path in manifest["files_sha256"], "Baseline metrics must be hash pinned")
        result["fixed_koelectra_baseline"] = read_json(contained(HERE, baseline_path))
        baseline_refs = result["fixed_koelectra_baseline"].get("references", {})
        result["xlmr_minus_fixed_baseline"] = {
            name: {model: {metric: values[metric]["f1"] - baseline[metric]["f1"]
                           for metric in ("partial", "exact")}
                   for model, baseline in baseline_refs.get(name, {}).items()}
            for name, values in result["references"].items()}
    result["limitations"] = ["Diagnostic references; not a new independent test.",
                              "Raw BIO predicts boundary/type only, not subject/level.",
                              "Type support below 30 is marked sample_insufficient."]
    dump(output / "metrics.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor"); doctor.add_argument("--gpu", action="store_true")
    prep = commands.add_parser("prepare")
    prep.add_argument("--output-dir", type=Path, default=HERE / "runs/bio-xlmr")
    prep.add_argument("--offline", action="store_true")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--run-dir", type=Path, required=True)
    evaluation.add_argument("--bio-dir", type=Path, help="Explicit prepared BIO directory; all pinned hashes are verified")
    evaluation.add_argument("--device", choices=("cuda", "cpu"), default="cpu")
    evaluation.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    if args.command == "doctor":
        _, _, _, summary = load_package()
        if args.gpu:
            import torch
            summary["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.command == "prepare":
        print(json.dumps(prepare(args.output_dir, args.offline), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(evaluate(args.run_dir, args.device, args.threads, args.bio_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValidationError, OSError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: {exc}")
