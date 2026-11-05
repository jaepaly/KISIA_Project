"""exp46 집계 — 검수 결과를 키로 풀어 정답별 사람 지지율 · 검수자 간 일치도를 낸다.

    python -X utf8 experiments/exp46-gold-recheck/tally.py --key C:/Users/dor12/kisia-private/exp46_key.json

reviews/<역할>.csv 를 전부 읽는다. 역할 C(원 라벨 작성자)는 사람 다수결·Fleiss κ 에서 빼고 따로 보고한다.
"""
import argparse
import collections
import csv
import hashlib
import itertools
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDS = ("official239", "previous_ai239", "conservative239")
CATS = ("X", "Y", "Z", "모두 틀림", "애매")
SEPARATE_ROLES = {"C"}     # official239 작성자 — 자기 라벨 지지 편향을 섞지 않는다


def normalize(choice):
    c = (choice or "").strip()
    if not c:
        return None
    if c.upper() in ("X", "Y", "Z"):
        return c.upper()
    c2 = c.replace(" ", "")
    if c2 in ("모두틀림", "모두틀림.", "전부틀림"):
        return "모두 틀림"
    if c2 in ("애매", "모름", "?"):
        return "애매"
    raise ValueError(f"선택 값 오류: {choice!r} (X/Y/Z/모두 틀림/애매 중 하나)")


def read_csv(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path}: 인코딩을 읽지 못함 — 엑셀에서 「CSV UTF-8」로 저장")
    return list(csv.DictReader(text.splitlines()))


def load_reviews(directory, key):
    items = {it["item_id"]: it for it in key["items"]}
    out = {}
    for path in sorted(Path(directory).glob("*.csv")):
        role = path.stem
        answers = {}
        for row in read_csv(path):
            iid = (row.get("item_id") or "").strip()
            if iid not in items:
                raise ValueError(f"{path.name}: 모르는 item_id {iid!r}")
            for L in "XYZ":
                want = items[iid]["candidates"].get(L, {}).get("label", "").strip()
                if (row.get(f"후보_{L}") or "").strip() != want:
                    raise ValueError(f"{path.name} {iid}: 후보_{L} 칸이 검수지와 다르다 — 후보 칸은 고치지 않는다")
            ch = normalize(row.get("선택"))
            if ch in ("X", "Y", "Z") and ch not in items[iid]["candidates"]:
                raise ValueError(f"{path.name} {iid}: 빈 후보 {ch} 를 골랐다")
            answers[iid] = ch
        out[role] = answers
    return out


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def supported(item, choice):
    if choice in ("X", "Y", "Z"):
        return set(item["candidates"][choice]["golds"])
    return set()


def support_table(items, choices):
    """choices: {item_id: 선택}. 분모 = 응답한 항목 전체(모두 틀림·애매 포함)."""
    answered = {i: c for i, c in choices.items() if c is not None}
    n = len(answered)
    res = {"answered": n}
    for g in GOLDS:
        k = sum(g in supported(items[i], c) for i, c in answered.items())
        res[g] = {"k": k, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}
    for cat in ("모두 틀림", "애매"):
        k = sum(c == cat for c in answered.values())
        res[cat] = {"k": k, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}
    return res


def weighted_support(items, choices, population):
    """층 가중 — 표본은 층마다 균등이라, 불일치 단위 전체(모집단)로 일반화할 때는 층 크기로 되돌린다.
    p_w = Σ W_h p_h, var = Σ W_h² p_h(1-p_h)/n_h (층 안 단순무작위 · 유한모집단 보정 생략)."""
    by = collections.defaultdict(list)
    for i, c in choices.items():
        if c is not None:
            by[items[i]["stratum"]].append((i, c))
    total = sum(population[h] for h in by)
    res = {}
    for g in GOLDS + ("모두 틀림", "애매"):
        p = var = 0.0
        for h, rows in by.items():
            w = population[h] / total
            hit = [(g in supported(items[i], c)) if g in GOLDS else (c == g) for i, c in rows]
            ph = sum(hit) / len(hit)
            p += w * ph
            var += w * w * ph * (1 - ph) / len(hit)
        se = math.sqrt(var)
        res[g] = {"rate": round(p, 4), "ci95": [round(max(0, p - 1.96 * se), 4), round(min(1, p + 1.96 * se), 4)]}
    res["strata_covered"] = sorted(by)
    res["population_units_covered"] = total
    return res


def majority(reviews, roles, item_ids):
    out = {}
    for i in item_ids:
        votes = [reviews[r][i] for r in roles if reviews[r].get(i) is not None]
        if not votes:
            out[i] = None
            continue
        top = collections.Counter(votes).most_common()
        out[i] = top[0][0] if len(top) == 1 or top[0][1] > top[1][1] else "애매"   # 동률은 애매로
    return out


def cohen(a, b):
    pairs = [(a[i], b[i]) for i in a if i in b and a[i] is not None and b[i] is not None]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "kappa": None}
    po = sum(x == y for x, y in pairs) / n
    ca, cb = collections.Counter(x for x, _ in pairs), collections.Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in CATS) / (n * n)
    return {"n": n, "agree": round(po, 4), "kappa": round((po - pe) / (1 - pe), 4) if pe < 1 else None}


def fleiss(reviews, roles, item_ids):
    rows = [[reviews[r][i] for r in roles] for i in item_ids]
    rows = [r for r in rows if all(c is not None for c in r)]
    m = len(roles)
    if m < 2 or not rows:
        return {"raters": m, "items": len(rows), "kappa": None}
    N = len(rows)
    counts = [collections.Counter(r) for r in rows]
    P_i = [(sum(v * v for v in c.values()) - m) / (m * (m - 1)) for c in counts]
    p_j = {k: sum(c[k] for c in counts) / (N * m) for k in CATS}
    Pbar, Pe = sum(P_i) / N, sum(v * v for v in p_j.values())
    return {"raters": m, "items": N, "kappa": round((Pbar - Pe) / (1 - Pe), 4) if Pe < 1 else None}


def by_stratum(items, choices):
    out = collections.defaultdict(lambda: collections.Counter())
    for i, c in choices.items():
        if c is None:
            continue
        it = items[i]
        side = "+".join(sorted(supported(it, c))) if c in ("X", "Y", "Z") else c
        out[it["stratum"]][side] += 1
    return {h: dict(v) for h, v in sorted(out.items())}


def tally(key, reviews, population):
    items = {it["item_id"]: it for it in key["items"]}
    ids = sorted(items)
    human = sorted(r for r in reviews if r not in SEPARATE_ROLES)
    result = {"items": len(ids), "reviewers": sorted(reviews), "pooled_roles": human,
              "per_reviewer": {r: {**support_table(items, reviews[r]), "by_stratum": by_stratum(items, reviews[r])}
                               for r in sorted(reviews)}}
    if human:
        maj = majority(reviews, human, ids)
        result["majority_pooled"] = {**support_table(items, maj), "by_stratum": by_stratum(items, maj),
                                     "stratum_weighted": weighted_support(items, maj, population)}
    result["fleiss_pooled"] = fleiss(reviews, human, ids)
    result["cohen_pairs"] = {f"{a}~{b}": cohen(reviews[a], reviews[b]) for a, b in itertools.combinations(sorted(reviews), 2)}
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--reviews", default=str(HERE / "reviews"))
    ap.add_argument("--summary", default=str(HERE / "units_summary.json"))
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    raw = Path(args.key).read_bytes()
    key = json.loads(raw)
    population = json.loads(Path(args.summary).read_text(encoding="utf-8"))["by_stratum"]
    reviews = load_reviews(args.reviews, key)
    if not reviews:
        sys.exit(f"검수 파일 없음: {args.reviews}/*.csv")
    result = {"key_sha256": hashlib.sha256(raw).hexdigest(), **tally(key, reviews, population)}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
