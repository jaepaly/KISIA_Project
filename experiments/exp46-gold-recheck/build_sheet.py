"""exp46 — 정답 3종 불일치 단위 추출 · 블라인드 검수지 생성.

공개(재현 가능) 부분: 불일치 단위 정의 · 층화 추출(SAMPLE_SEED).
비공개 부분: 항목 순서 · 후보 X/Y/Z 배정 · 묶음 대표 표시 선택 — 키 파일의 salt 로만 재현된다.

    python -X utf8 experiments/exp46-gold-recheck/build_sheet.py summary
    python -X utf8 experiments/exp46-gold-recheck/build_sheet.py build --key-out C:/Users/dor12/kisia-private/exp46_key.json

정답 파일(exp44 data/)과 data/corpus/v0/posts/ 는 읽기만 한다.
"""
import argparse
import collections
import csv
import hashlib
import json
import random
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOLD_DIR = ROOT / "experiments" / "exp44-xlmr-handoff" / "data"
POSTS_DIR = ROOT / "data" / "corpus" / "v0" / "posts"
GOLDS = ("official239", "previous_ai239", "conservative239")
SAMPLE_SEED = 20261105          # 공개 — 층화 추출만 정한다
N_ITEMS = 60
LETTERS = "XYZ"
NONE_LABEL = "(스팬 없음)"
CHOICES = ("X", "Y", "Z", "모두 틀림", "애매")
SHEET_COLUMNS = ["item_id", "post_id", "채널", "문맥", "후보_X", "후보_Y", "후보_Z", "선택", "메모"]


# ── 읽기 ────────────────────────────────────────────────────────────────
def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_golds(gold_dir=GOLD_DIR):
    golds = {}
    for name in GOLDS:
        rows = read_jsonl(Path(gold_dir) / f"{name}.jsonl")
        golds[name] = {r["post_id"]: r["spans"] for r in rows}
    ids = [set(g) for g in golds.values()]
    if not all(s == ids[0] for s in ids):
        sys.exit("세 정답의 글 목록이 다르다")
    return golds


def load_texts(post_ids, posts_dir=POSTS_DIR):
    want, texts = set(post_ids), {}
    for path in sorted(Path(posts_dir).glob("*.jsonl")):
        for row in read_jsonl(path):
            if row.get("post_id") in want:
                texts[row["post_id"]] = row["texts"]
    missing = want - set(texts)
    if missing:
        sys.exit(f"원문 없음: {sorted(missing)[:5]}")
    return texts


# ── 계약 매칭 ───────────────────────────────────────────────────────────
def iou(a, b):
    if a["text_id"] != b["text_id"]:
        return 0.0
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return inter / (max(a["end"], b["end"]) - min(a["start"], b["start"]))


def overlaps(a, b):
    return a["text_id"] == b["text_id"] and min(a["end"], b["end"]) > max(a["start"], b["start"])


def match_count(xs, ys):
    """exp44 handoff.match_counts 와 같은 규칙: 유형 일치 + IoU>=.5, IoU 내림차순 탐욕 1:1."""
    pairs = sorted(((iou(a, b), i, j) for i, a in enumerate(xs) for j, b in enumerate(ys)
                    if a["type"] == b["type"] and iou(a, b) >= .5), reverse=True)
    ui, uj = set(), set()
    for _, i, j in pairs:
        if i not in ui and j not in uj:
            ui.add(i); uj.add(j)
    return len(ui)


def equivalent(xs, ys):
    """두 스팬 집합이 채점상 같은가 — 1:1 로 전부 짝지어지면 F1 에서 구별되지 않는다."""
    return len(xs) == len(ys) and match_count(xs, ys) == len(xs)


# ── 불일치 단위 ─────────────────────────────────────────────────────────
def components(spans_by_gold):
    """세 정답의 스팬을 노드로, 같은 채널에서 한 글자라도 겹치면 간선(유형 무관). 연결 성분 = 단위."""
    nodes = [(g, s) for g in GOLDS for s in spans_by_gold[g]]
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if overlaps(nodes[i][1], nodes[j][1]):
                parent[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for i, node in enumerate(nodes):
        groups[find(i)].append(node)
    out = []
    for members in groups.values():
        per = {g: sorted((s for gg, s in members if gg == g), key=lambda s: (s["start"], s["end"])) for g in GOLDS}
        out.append(per)
    return sorted(out, key=lambda per: min((s["text_id"], s["start"]) for g in GOLDS for s in per[g]))


def partition(per):
    """채점상 같은 정답끼리 묶는다. 반환: 묶음 목록(각 묶음은 정답 이름 튜플) · 패턴 이름."""
    eq = {(a, b): equivalent(per[a], per[b]) for i, a in enumerate(GOLDS) for b in GOLDS[i + 1:]}
    o, p, c = GOLDS
    n_eq = sum(eq.values())
    if n_eq == 3:
        return [GOLDS], "agree"
    if n_eq == 0:
        return [(o,), (p,), (c,)], "all_differ"
    if n_eq == 1:
        (a, b), = [k for k, v in eq.items() if v]
        rest = next(g for g in GOLDS if g not in (a, b))
        short = {o: "O", p: "P", c: "C"}
        return [(a, b), (rest,)], f"{short[rest]}_alone"
    # 비이행(두 쌍만 같음) — 세 묶음으로 두고 따로 센다
    return [(o,), (p,), (c,)], "intransitive"


def kind(per, classes):
    """불일치 성격 — 혼자 갈린 정답 기준.
    lone_extra: 혼자만 스팬이 있음 · lone_missing: 혼자만 스팬이 없음 ·
    type: 겹치는데 유형 집합이 다름 · boundary: 그 외(경계 IoU<.5 · 분할 수 차이)."""
    lone = [c[0] for c in classes if len(c) == 1]
    if any(not per[g] for g in GOLDS):
        if len(lone) == 1:
            return "lone_missing" if not per[lone[0]] else "lone_extra"
        return "missing"
    types = [frozenset(s["type"] for s in per[g]) for g in GOLDS]
    if len(set(types)) > 1:
        return "type"
    return "boundary"


def build_units(golds, texts):
    units = []
    for pid in sorted(golds[GOLDS[0]]):
        per_post = {g: golds[g][pid] for g in GOLDS}
        for per in components(per_post):
            classes, pattern = partition(per)
            units.append({"post_id": pid, "per": per, "classes": classes, "pattern": pattern,
                          "kind": kind(per, classes) if pattern != "agree" else "agree"})
    for i, u in enumerate(units):
        u["unit_id"] = f"U{i:04d}"
    return units


def summarize(units):
    dis = [u for u in units if u["pattern"] != "agree"]
    return {"posts": len({u["post_id"] for u in units}), "units_total": len(units),
            "units_agree": len(units) - len(dis), "units_disagree": len(dis),
            "by_pattern": dict(sorted(collections.Counter(u["pattern"] for u in dis).items())),
            "by_kind": dict(sorted(collections.Counter(u["kind"] for u in dis).items())),
            "by_stratum": dict(sorted(collections.Counter(stratum(u) for u in dis).items()))}


# ── 층화 추출 (공개 seed) ───────────────────────────────────────────────
def stratum(u):
    return f"{u['pattern']}|{u['kind']}"


def stratified_sample(units, n=N_ITEMS, seed=SAMPLE_SEED):
    """층 = 패턴(어느 정답이 혼자 갈리나) × 성격(lone_extra/lone_missing/type/boundary).
    층마다 균등 배분하고, 나머지 몫은 seed 로 섞은 층 순서대로 1개씩, 모자란 층의 몫은 남은 층에 돌린다.
    표본이 층마다 균등이라 모집단 비율과 다르다 — 일반화 수치는 tally.py 가 층 가중으로 따로 낸다."""
    rng = random.Random(seed)
    strata = collections.defaultdict(list)
    for u in units:
        if u["pattern"] != "agree":
            strata[stratum(u)].append(u)
    names = sorted(strata)
    order = list(names)
    rng.shuffle(order)
    quota = {s: 0 for s in names}
    remaining = n
    while remaining > 0:
        open_ = [s for s in order if quota[s] < len(strata[s])]
        if not open_:
            break
        base = min(len(open_), remaining)
        for s in open_[:base]:
            quota[s] += 1
            remaining -= 1
    picked = []
    for s in names:
        pool = sorted(strata[s], key=lambda u: u["unit_id"])
        picked.extend(rng.sample(pool, quota[s]))
    return picked, quota


# ── 검수지 (비공개 salt) ────────────────────────────────────────────────
def label(spans):
    if not spans:
        return NONE_LABEL
    out = " + ".join(f"「{s['text']}」 {s['type']}/{s['level']}" for s in spans)
    return out.replace("\r", "").replace("\n", " ⏎ ")


def context(text, spans, pad=60, cap=420):
    lo, hi = min(s["start"] for s in spans), max(s["end"] for s in spans)
    a = lo
    while a > 0 and text[a - 1] not in ".?!\n" and lo - a < cap // 2:
        a -= 1
    b = hi
    while b < len(text) and text[b] not in ".?!\n" and b - hi < cap // 2:
        b += 1
    a, b = max(0, a - pad), min(len(text), b + 1 + pad)
    body = text[a:lo] + "【" + text[lo:hi] + "】" + text[hi:b]
    body = ("…" if a > 0 else "") + body + ("…" if b < len(text) else "")
    return body.replace("\r", "").replace("\n", " ⏎ ")


def make_sheet(picked, texts, salt):
    rng = random.Random(hashlib.sha256(("exp46:" + salt).encode()).hexdigest())
    order = list(picked)
    rng.shuffle(order)
    rows, key_items = [], []
    for idx, u in enumerate(order, 1):
        item_id = f"G{idx:02d}"
        all_spans = [s for g in GOLDS for s in u["per"][g]]
        channel = all_spans[0]["text_id"]
        classes = list(u["classes"])
        rng.shuffle(classes)
        cands = {}
        for letter, cls in zip(LETTERS, classes):
            shown = u["per"][rng.choice(sorted(cls))]   # 같은 묶음 안 표시본도 무작위
            cands[letter] = {"golds": sorted(cls), "label": label(shown)}
        rows.append({"item_id": item_id, "post_id": u["post_id"], "채널": channel,
                     "문맥": context(texts[u["post_id"]][channel], all_spans),
                     **{f"후보_{L}": cands[L]["label"] if L in cands else "" for L in LETTERS},
                     "선택": "", "메모": ""})
        key_items.append({"item_id": item_id, "unit_id": u["unit_id"], "post_id": u["post_id"],
                          "pattern": u["pattern"], "kind": u["kind"], "stratum": stratum(u), "candidates": cands,
                          "spans": {g: u["per"][g] for g in GOLDS}})
    rows.sort(key=lambda r: r["item_id"])
    return rows, key_items


def write_sheet(rows, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("summary", help="불일치 단위 통계와 층 구성만 출력(공개 정보)")
    b = sub.add_parser("build", help="검수지와 비공개 키 생성")
    b.add_argument("--key-out", required=True, help="저장소 밖 경로")
    b.add_argument("--salt", help="재현용. 생략하면 새로 만든다(키 파일에 기록)")
    b.add_argument("--sheet", default=str(HERE / "sheet.csv"))
    args = ap.parse_args(argv)

    golds = load_golds()
    texts = load_texts(golds[GOLDS[0]])
    units = build_units(golds, texts)
    picked, quota = stratified_sample(units)
    summary = summarize(units)
    summary["sample"] = {"seed": SAMPLE_SEED, "n": len(picked), "quota_by_stratum": quota,
                         "unit_ids": sorted(u["unit_id"] for u in picked)}
    if args.cmd == "summary":
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return
    key_out = Path(args.key_out).resolve()
    if ROOT in key_out.parents:
        sys.exit("키는 저장소 밖에 둔다")
    salt = args.salt or secrets.token_hex(16)
    rows, key_items = make_sheet(picked, texts, salt)
    write_sheet(rows, args.sheet)
    (HERE / "units_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    key_out.parent.mkdir(parents=True, exist_ok=True)
    key = {"experiment": "exp46-gold-recheck", "salt": salt, "sample_seed": SAMPLE_SEED,
           "golds": list(GOLDS), "items": key_items}
    data = json.dumps(key, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    key_out.write_bytes(data)
    print(f"sheet: {args.sheet}  items={len(rows)}")
    print(f"key: {key_out}  sha256={hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
