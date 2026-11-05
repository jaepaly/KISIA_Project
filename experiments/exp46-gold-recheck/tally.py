"""exp46 집계 — 검수 결과를 키로 풀어 정답별 사람 지지율 · 검수자 간 일치도를 낸다.

    python -X utf8 experiments/exp46-gold-recheck/tally.py --key C:/Users/dor12/kisia-private/exp46_key.json

reviews/<역할>.csv (역할 = A~E 대문자 한 글자)를 전부 읽는다.
역할 C(official239 작성자)는 다수결·Fleiss κ 에서 빼고 따로 보고한다.

지지의 뜻: 검수자가 고른 후보를 「참」으로 놓았을 때, 계약 채점(유형 일치 + IoU>=.5, 1:1)으로
그 후보와 전부 짝지어지는 정답이 그 항목에서 지지받는다 — F1 이 실제로 쓰는 의미 그대로다.
"""
import argparse
import collections
import csv
import hashlib
import itertools
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_sheet import GOLDS, SHEET_COLUMNS, equivalent  # noqa: E402

CATS = ("X", "Y", "Z", "모두 틀림", "애매")
SEPARATE_ROLES = {"C"}          # official239 작성자 — 자기 라벨 지지 편향을 섞지 않는다
ROLE_RE = re.compile(r"^[A-E]$")
EXPECTED_KEY_SHA256 = "4d5c1febd7d53816fdca979ac0a666a4e6be1ef9305517cd8315457acb742ee8"   # README 에 사전 고정한 값과 같아야 한다
MIN_PER_STRATUM = 5             # 층마다 판정(다수결 성립) 최소 수 — 미달이면 주 지표를 내지 않는다
NO_MAJORITY = "과반 없음"


def normalize(choice):
    c = (choice or "").strip()
    if not c:
        return None
    if c.upper() in ("X", "Y", "Z"):
        return c.upper()
    c2 = c.replace(" ", "")
    if c2 in ("모두틀림", "전부틀림", "둘다틀림"):  # A 검수가 「둘 다 틀림」으로 적음 — 후보가 둘뿐이라 같은 뜻
        return "모두 틀림"
    if c2 == "애매":
        return "애매"
    raise ValueError(f"선택 값 오류: {choice!r} (X/Y/Z/모두 틀림/애매 중 하나)")


def read_csv(path):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{Path(path).name}: UTF-8 이 아니다 — 엑셀에서 「CSV UTF-8(쉼표로 분리)」로 다시 저장"
                         " (일반 CSV 는 ⏎·이모지가 깨진다)") from None
    rows = list(csv.DictReader(text.splitlines()))
    if rows and "선택" not in rows[0]:
        raise ValueError(f"{Path(path).name}: 「선택」 열이 없다")
    return rows


def load_reviews(directory, key, sheet_rows=None):
    """sheet_rows 를 주면 item_id 외 표시 칸(post_id·채널·문맥·후보)도 원본 검수지와 같은지 본다."""
    items = {it["item_id"]: it for it in key["items"]}
    sheet = {r["item_id"]: r for r in sheet_rows} if sheet_rows else None
    out = {}
    for path in sorted(Path(directory).glob("*.csv")):
        role = path.stem
        if not ROLE_RE.match(role):
            raise ValueError(f"{path.name}: 파일 이름은 역할 한 글자(A~E 대문자)여야 한다 — 사본·백업은 reviews/ 밖에 둔다")
        answers = {}
        for row in read_csv(path):
            iid = (row.get("item_id") or "").strip()
            if iid not in items:
                raise ValueError(f"{path.name}: 모르는 item_id {iid!r}")
            if iid in answers:
                raise ValueError(f"{path.name}: item_id {iid} 가 두 번 나온다")
            for L in "XYZ":
                want = items[iid]["candidates"].get(L, {}).get("label", "").strip()
                if (row.get(f"후보_{L}") or "").strip() != want:
                    raise ValueError(f"{path.name} {iid}: 후보_{L} 칸이 검수지와 다르다 — 후보 칸은 고치지 않는다")
            if sheet:
                for col in ("post_id", "채널", "문맥"):
                    if (row.get(col) or "").strip() != (sheet[iid].get(col) or "").strip():
                        raise ValueError(f"{path.name} {iid}: {col} 칸이 검수지와 다르다")
            ch = normalize(row.get("선택"))
            if ch in ("X", "Y", "Z") and ch not in items[iid]["candidates"]:
                raise ValueError(f"{path.name} {iid}: 빈 후보 {ch} 를 골랐다")
            answers[iid] = ch
        missing = set(items) - set(answers)
        if missing:
            raise ValueError(f"{path.name}: 행이 빠졌다 {sorted(missing)[:5]} — 검수지를 통째로 복사해 쓴다")
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
    """고른 후보를 참으로 놓고 계약 채점으로 전부 짝지어지는 정답들."""
    if choice not in ("X", "Y", "Z"):
        return set()
    truth = item["candidates"][choice]["spans"]
    return {g for g in GOLDS if equivalent(item["spans"][g], truth)}


def support_table(items, choices):
    """원시 비율(층 가중 아님). 분모 = 응답한 항목 전체(모두 틀림·애매·과반 없음 포함)."""
    answered = {i: c for i, c in choices.items() if c is not None}
    n = len(answered)
    res = {"answered": n}
    for g in GOLDS:
        k = sum(g in supported(items[i], c) for i, c in answered.items())
        res[g] = {"k": k, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}
    for cat in ("모두 틀림", "애매", NO_MAJORITY):
        k = sum(c == cat for c in answered.values())
        res[cat] = {"k": k, "rate": round(k / n, 4) if n else None}
    return res


def _stratified(values_by_stratum, population, z=1.96):
    """층화 평균과 설계기반 CI. var = Σ W_h² (1 − n_h/N_h) s_h² / n_h.
    작은 층에서 전부 같은 값이면 s_h²=0 이 되어 CI 가 무너지므로, 층마다 값의 범위 양끝(최소·최대 가능값)을
    가짜 관측 하나씩 더해 s_h² 를 계산한다(Agresti–Caffo 식 보정 · 보수적). 점추정에는 넣지 않는다."""
    total = sum(population.values())
    est = var = 0.0
    for h, N_h in population.items():
        vals = values_by_stratum.get(h, [])
        n_h, w = len(vals), N_h / total
        mean = sum(vals) / n_h
        lo, hi = values_by_stratum["__range__"]
        padded = vals + [lo, hi]
        m2 = sum(padded) / len(padded)
        s2 = sum((v - m2) ** 2 for v in padded) / (len(padded) - 1)
        est += w * mean
        var += w * w * max(0.0, 1 - n_h / N_h) * s2 / n_h
    se = math.sqrt(var)
    return round(est, 4), [round(est - z * se, 4), round(est + z * se, 4)]


def weighted_support(items, choices, population, min_per_stratum=MIN_PER_STRATUM):
    """층 크기로 가중한 불일치 단위 전체(355) 추정. 층마다 판정이 min_per_stratum 미만이면 status=insufficient
    로 두고 수치를 내지 않는다 — 응답이 없는 층을 빼고 가중치를 다시 맞추면 추정 대상이 조용히 바뀐다."""
    by = collections.defaultdict(list)
    for i, c in choices.items():
        if c is not None:
            by[items[i]["stratum"]].append((i, c))
    short = {h: len(by.get(h, [])) for h in population if len(by.get(h, [])) < min_per_stratum}
    if short:
        return {"status": "insufficient", "strata_short": short, "min_per_stratum": min_per_stratum}
    res = {"status": "ok"}
    for g in GOLDS + ("모두 틀림", "애매", NO_MAJORITY):
        vals = {h: [float(g in supported(items[i], c)) if g in GOLDS else float(c == g) for i, c in rows]
                for h, rows in by.items()}
        vals["__range__"] = (0.0, 1.0)
        rate, ci = _stratified(vals, population)
        res[g] = {"rate": rate, "ci95": [max(0.0, ci[0]), min(1.0, ci[1])]}
    # 짝지은 차이: 항목마다 (previous 지지) − (official 지지) ∈ {−1,0,1}
    d = {h: [float("previous_ai239" in supported(items[i], c)) - float("official239" in supported(items[i], c))
             for i, c in rows] for h, rows in by.items()}
    d["__range__"] = (-1.0, 1.0)
    rate, ci = _stratified(d, population)
    res["diff_previous_minus_official"] = {"estimate": rate, "ci95": ci}
    return res


def majority(reviews, roles, item_ids):
    """과반(> 절반) 득표만 채택. 과반이 없으면 NO_MAJORITY — 누구도 「애매」라 하지 않은 동률을 애매로 세지 않는다."""
    out = {}
    for i in item_ids:
        votes = [reviews[r][i] for r in roles if reviews[r].get(i) is not None]
        if not votes:
            out[i] = None
            continue
        top, k = collections.Counter(votes).most_common(1)[0]
        out[i] = top if k * 2 > len(votes) else NO_MAJORITY
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
    rows = [[reviews[r].get(i) for r in roles] for i in item_ids]
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
    out = collections.defaultdict(collections.Counter)
    for i, c in choices.items():
        if c is None:
            continue
        side = "+".join(sorted(supported(items[i], c))) if c in ("X", "Y", "Z") else c
        out[items[i]["stratum"]][side] += 1
    return {h: dict(v) for h, v in sorted(out.items())}


def abstain_rate(reviews, roles):
    """검수자들이 실제로 쓴 「모두 틀림 + 애매」 비율의 평균(다수결 집계 규칙의 영향을 받지 않는다)."""
    rates = []
    for r in roles:
        ans = [c for c in reviews[r].values() if c is not None]
        if ans:
            rates.append(sum(c in ("모두 틀림", "애매") for c in ans) / len(ans))
    return round(sum(rates) / len(rates), 4) if rates else None


def tally(key, reviews, population):
    items = {it["item_id"]: it for it in key["items"]}
    ids = sorted(items)
    human = sorted(r for r in reviews if r not in SEPARATE_ROLES)
    result = {"items": len(ids), "reviewers": sorted(reviews), "pooled_roles": human,
              "per_reviewer": {r: {**support_table(items, reviews[r]), "by_stratum": by_stratum(items, reviews[r]),
                                   "stratum_weighted": weighted_support(items, reviews[r], population)}
                               for r in sorted(reviews)}}
    if human:
        maj = majority(reviews, human, ids)
        result["majority_pooled"] = {**support_table(items, maj), "by_stratum": by_stratum(items, maj),
                                     "stratum_weighted": weighted_support(items, maj, population)}
        result["abstain_rate_pooled"] = abstain_rate(reviews, human)
    result["fleiss_pooled"] = fleiss(reviews, human, ids)
    result["cohen_pairs"] = {f"{a}~{b}": cohen(reviews[a], reviews[b]) for a, b in itertools.combinations(sorted(reviews), 2)}
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--reviews", default=str(HERE / "reviews"))
    ap.add_argument("--summary", default=str(HERE / "units_summary.json"))
    ap.add_argument("--sheet", default=str(HERE / "sheet.csv"))
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    raw = Path(args.key).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_KEY_SHA256:
        sys.exit(f"키 해시가 사전 고정 값과 다르다: {digest}")
    key = json.loads(raw)
    population = json.loads(Path(args.summary).read_text(encoding="utf-8"))["by_stratum"]
    with open(args.sheet, encoding="utf-8-sig", newline="") as f:
        sheet_rows = list(csv.DictReader(f))
    if [r["item_id"] for r in sheet_rows] != sorted(it["item_id"] for it in key["items"]) or \
            list(sheet_rows[0]) != SHEET_COLUMNS:
        sys.exit("sheet.csv 와 키가 맞지 않는다")
    reviews = load_reviews(args.reviews, key, sheet_rows)
    if not reviews:
        sys.exit(f"검수 파일 없음: {args.reviews}/*.csv")
    result = {"key_sha256": digest, **tally(key, reviews, population)}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
