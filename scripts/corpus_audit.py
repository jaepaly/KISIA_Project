"""코퍼스 감사 — validate.py 가 보지 않는 인물 간·코퍼스 단위 점검.

validate.py 는 인물 하나가 스키마와 계약에 맞는지 본다. 이 스크립트는
**여러 명을 한꺼번에 놓고 봐야만 보이는 것**을 본다. 빈 축, 쏠린 축,
선언과 실물의 어긋남, 그리고 계약 문서 사이의 불일치다.

전부 진단이다. 통과/실패를 판정하지 않는다 — 기준선이 아직 정해지지
않은 항목이 섞여 있어서다. 어떤 값이 나오면 문제인지는
docs/corpus-audit.md 에 항목마다 적어뒀다.

실행:
    python scripts/corpus_audit.py
    python scripts/corpus_audit.py --personas data/corpus/v0/personas
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTRS = ["age", "sex", "location", "occupation", "family", "commute", "income"]

# 나이를 「값 그대로」 적은 표현. label-schema §4-1 은 한글 수사도 explicit 으로 본다
# ("마흔여덟"은 explicit 이며, 기존 도구가 못 잡는 explicit 이다).
AGE_VALUE = re.compile(
    r"\d+\s*[살세]|\d{2}|스물|서른|마흔|쉰|예순|일흔|여든|아흔|"
    r"열[한두세네다섯여섯일곱여덟아홉]"
)

# 함정 문형 분류.
#
# ⚠️ 표면형(살아서/산다)으로 세는 것은 **근사**다. persona-design §4-4-1 이
#    2026-08-31 부터 note 에 「통로=근무지 · 관계=④ 인접」을 구조로 남기므로
#    그쪽을 먼저 읽고, 없는 것만 표면형으로 떨어진다.
LIVES_IN = re.compile(r"살아서|살고|산다|살아")
TRAP_VIA_RE = re.compile(r"통로\s*=\s*((?:[^\s,)]|·(?=\S))+)")


def load(personas_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(personas_dir.glob("*.json"))]


def head(n: int, title: str) -> None:
    print(f"\n{'-' * 64}\n{n}. {title}\n{'-' * 64}")


# ── 1. 거주지가 지명 사전으로 풀리는가 ───────────────────────────────
def audit_geo(ps: list[dict]) -> None:
    head(1, "거주지 조회 (이슈 #115)")
    d = json.loads((ROOT / "data/dict/admin/regions.json").read_text(encoding="utf-8"))
    R, NI = d["regions"], d["name_index"]
    full = {v["full_name"] for v in R.values()}
    sido = {v["name"] for v in R.values() if v.get("level") == "sido"}

    ok, miss, wrong = [], [], []
    for p in ps:
        loc = (p.get("ground_truth", {}).get("location") or "").strip()
        if not loc:
            continue
        if loc in full:
            ok.append(p["id"])
        elif loc.split()[0] not in sido:
            wrong.append((p["id"], loc, "시도명이 사전에 없다 — 행정구역 개편"))
        else:
            codes = NI.get(loc.split()[-1])
            if not codes:
                miss.append((p["id"], loc, "이름이 사전에 없다 — 법정동일 수 있다"))
            elif len(codes) > 1:
                miss.append((p["id"], loc, f"후보 {len(codes)}개 — 맥락으로 좁혀야 한다"))
            else:
                got = R[codes[0]]["full_name"]
                # 시도까지 같으면 그 사이(시군구) 이름이 어긋난 것이다. 개편이 흔한 자리다.
                same_sido = got.startswith(loc.split()[0])
                label = "구 이름이 다르다 -> " if same_sido else "조용히 "
                wrong.append((p["id"], loc, label + got))

    print(f"  풀림 {len(ok)} · 못 풀림 {len(miss)} · 엉뚱한 곳 {len(wrong)}   / {len(ps)}명")
    for pid, loc, why in wrong:
        print(f"    [!] {pid:<5} {loc:<27} {why}")
    for pid, loc, why in miss:
        print(f"    [x] {pid:<5} {loc:<27} {why}")


# ── 2. 속성별 단서 커버리지 ──────────────────────────────────────────
def audit_attr_coverage(ps: list[dict]) -> None:
    head(2, "속성별 clue_plan 커버리지 (이슈 #116)")
    miss = collections.Counter()
    for p in ps:
        have = {c.get("attr") for c in p.get("clue_plan") or []}
        for a in ATTRS:
            if a not in have:
                miss[a] += 1
    for a in ATTRS:
        n = miss[a]
        bar = "#" * round(18 * n / max(1, len(ps)))
        flag = "  [!] 측정 표본이 거의 없다" if n >= len(ps) * 0.8 else ""
        print(f"    {a:<11} 단서 없는 인물 {n:>2}/{len(ps)}  {bar}{flag}")


# ── 3. 함정 문형이 쏠려 있는가 ───────────────────────────────────────
def audit_trap_variety(ps: list[dict]) -> None:
    head(3, "함정 문형 다양성 (이슈 #116)")
    forms: collections.Counter = collections.Counter()
    fallback = 0
    for p in ps:
        for c in p.get("clue_plan") or []:
            if c.get("attr") != "location" or "함정" not in str(c.get("note", "")):
                continue
            m = TRAP_VIA_RE.search(str(c.get("note", "")))
            if m:
                forms[m.group(1)] += 1
            else:
                # note 에 통로가 없다 — 표면형으로 근사한다
                fallback += 1
                forms["(미표기) 거주형" if LIVES_IN.search(c.get("clue", ""))
                      else "(미표기) 그 밖"] += 1
    tot = sum(forms.values()) or 1
    for f, n in forms.most_common():
        print(f"    {f:<16} {n:>3}건  {100 * n / tot:>3.0f}%  {'#' * round(40 * n / tot)}")
    top = forms.most_common(1)
    if top and top[0][1] / tot > 0.5:
        print(f"    [!] 한 통로가 {100 * top[0][1] / tot:.0f}% 다. 표면형을 외우면 "
              "귀속 추론 없이도 점수가 나온다")
    if fallback:
        print(f"    [!] note 에 통로가 없는 함정 {fallback}건 — 표면형으로 근사했다. "
              "§4-4-1 형식으로 적으면 정확해진다")


# ── 4. 프로필 단서가 실제 프로필에 들어 있는가 ───────────────────────
def audit_profile(ps: list[dict]) -> None:
    head(4, "profile_bio 단서 <-> account.profile_intro")
    bad, n = [], 0
    for p in ps:
        intro = (p.get("account") or {}).get("profile_intro", "")
        for c in p.get("clue_plan") or []:
            if c.get("text_id") != "profile_bio":
                continue
            n += 1
            if c.get("clue", "").strip() not in intro:
                bad.append((p["id"], intro, c.get("clue", "")))
    print(f"    {n - len(bad)}/{n} 일치")
    for pid, intro, clue in bad:
        print(f"    [x] {pid:<5} 프로필={intro!r}")
        print(f"    {'':<9} 단서  ={clue!r}  <- 이 단서는 코퍼스에 안 나타난다")


# ── 5. explicit 나이 단서에 값이 있는가 ──────────────────────────────
def audit_explicit_age(ps: list[dict]) -> None:
    head(5, "explicit 나이 단서에 실제 값이 있는가 (label-schema 4-1)")
    bad, n = [], 0
    for p in ps:
        for c in p.get("clue_plan") or []:
            if c.get("attr") == "age" and c.get("level") == "explicit":
                n += 1
                if not AGE_VALUE.search(c.get("clue", "")):
                    bad.append((p["id"], c.get("clue", "")))
    print(f"    {n - len(bad)}/{n} 에 수사가 있다")
    for pid, clue in bad:
        print(f"    [!] {pid:<5} {clue[:50]}  <- 값이 없으면 explicit 이 아니다")


# ── 6. 카드 사용 현황 ────────────────────────────────────────────────
def audit_cards(ps: list[dict], cards_dir: Path) -> None:
    head(6, "리얼리즘 카드 사용 현황")
    used: collections.Counter = collections.Counter()
    for p in ps:
        for c in p.get("card_ref") or []:
            used[c] += 1
    have = sorted({f.name.split("_")[0].removesuffix(".md")
                   for f in cards_dir.glob("S*.md")}, key=lambda s: int(s[1:]))
    idle = [c for c in have if c not in used]
    print(f"    카드 {len(have)}장 · 쓰인 것 {len(have) - len(idle)}장")
    print("    " + "  ".join(f"{c}x{used[c]}" if used[c] else f"{c}--" for c in have))
    if idle:
        print(f"    [!] 미사용: {', '.join(idle)}")


# ── 7. 축 분포 ───────────────────────────────────────────────────────
def audit_distribution(ps: list[dict]) -> None:
    head(7, "축 분포 (persona-design.md 7)")
    dec: collections.Counter = collections.Counter()
    sex: collections.Counter = collections.Counter()
    sido: collections.Counter = collections.Counter()
    kind: collections.Counter = collections.Counter()
    for p in ps:
        g = p.get("ground_truth", {})
        if g.get("age"):
            dec[g["age"] // 10 * 10] += 1
        sex[g.get("sex")] += 1
        loc = (g.get("location") or "").split()
        if loc:
            sido[loc[0]] += 1
            kind["군·읍면" if loc[-1].endswith(("면", "읍")) else "시·동"] += 1
    print("    연령대  " + " · ".join(f"{k}대 {v}" for k, v in sorted(dec.items())))
    print("    성별    " + " · ".join(f"{k} {v}" for k, v in sorted(sex.items())))
    print("    거주형  " + " · ".join(f"{k} {v}" for k, v in sorted(kind.items())))
    print(f"    시도    {len(sido)}개 — " + " · ".join(
        f"{k.replace('특별자치도', '').replace('광역시', '').replace('특별시', '')} {v}"
        for k, v in sido.most_common()))
    for lo in range(10, 80, 10):
        if dec.get(lo, 0) == 0:
            print(f"    [!] {lo}대가 없다")


# ── 8. 설계한 단서가 생성기까지 가는가 ───────────────────────────────
def audit_reach(ps: list[dict]) -> None:
    head(8, "설계 단서의 생성기 도달률 (PR #112)")
    tot = over = prof = 0
    ch: collections.Counter = collections.Counter()
    for p in ps:
        cp = p.get("clue_plan") or []
        tot += len(cp)
        prof += sum(1 for c in cp if c.get("post") is None)
        cnt = collections.Counter(c["post"] for c in cp if c.get("post") is not None)
        over += sum(v - 1 for v in cnt.values() if v > 1)
        for c in cp:
            t = str(c.get("text_id", "body"))
            ch["photo_caption:N" if t.startswith("photo_caption") else t] += 1
    print(f"    설계 {tot}건")
    print(f"      한 글에 둘 이상  {over:>3}건  <- generate.py 가 리스트로 받아야 한다")
    print(f"      프로필 단서      {prof:>3}건  <- profile 레코드로 나가야 한다")
    print("    채널  " + " · ".join(f"{k} {v}" for k, v in ch.most_common()))


def main() -> int:
    ap = argparse.ArgumentParser(description="코퍼스 감사")
    ap.add_argument("--personas", default="data/corpus/v0/personas")
    ap.add_argument("--cards", default="data/realism/cards")
    a = ap.parse_args()
    pdir, cdir = ROOT / a.personas, ROOT / a.cards
    ps = load(pdir)
    print(f"코퍼스 감사 — 인물 {len(ps)}명  ({a.personas})")
    print("판정하지 않는다. 무엇이 나오면 문제인지는 docs/corpus-audit.md 참조")
    audit_geo(ps)
    audit_attr_coverage(ps)
    audit_trap_variety(ps)
    audit_profile(ps)
    audit_explicit_age(ps)
    audit_cards(ps, cdir)
    audit_distribution(ps)
    audit_reach(ps)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
