"""측정 결과 채점.

⚠️ 초판의 지표 셋이 틀렸다. Codex 교차검토(2026-08-31)에서 나왔고 실측으로 확인했다.

  ① 「단서 있는 칸을 abstain 안 했나」만 보면 **무조건 추론하는 모델이 만점**이다.
     계약은 기권도 정상 동작이라 양성·음성을 함께 봐야 한다 → 전체 245칸 정확도로 바꿨다.
     그리고 179/35 = 5.11 이 최대치라 「5.03/7」을 §4 의 「7속성 중 5개 적중」 충족
     근거로 쓸 수 없다. 그건 값 적중 수이고 이건 아니다.
  ② 「evidence 가 실재하는 span_id 인가」는 참조 무결성일 뿐이다. subject=other 인
     스팬 id 도 «유효»로 득점한다 → 실재 · self · 해당 속성까지 보는 의미상 정확도로 바꿨다.
  ③ 형식 준수율을 JSON 파싱 여부로만 셌다. Ollama 의 format 은 구조만 강제하고
     값 제약(0~1 등)은 강제하지 않는다 — stage2-io.schema.json 이 이미 경고해뒀다.
     실제로 1.7b 가 confidence 를 30~80 으로 냈다.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")


def score(items: dict, raw: list[dict]) -> dict:
    r = {k: 0 for k in ("칸적중", "칸분모", "양성적중", "양성분모", "기권적중", "기권분모",
                        "근거적중", "근거분모", "실재", "함정오용인물", "함정보유인물",
                        "구조통과", "값위반칸", "값위반인물", "프로브적중", "프로브분모",
                        "토큰", "n")}
    r["초"] = 0.0
    r["함정오용목록"] = []
    for rec in raw:
        it = items[rec["persona_id"]]
        r["n"] += 1
        r["초"] += rec["meta"]["sec"]
        r["토큰"] += rec["meta"]["eval_tokens"]
        f = rec.get("findings")
        if not f:
            continue
        r["구조통과"] += 1
        by_id = {s["span_id"]: s for s in it["spans"]}
        trap = {s["span_id"] for s in it["spans"] if s["subject"] == "other"}
        if trap:
            r["함정보유인물"] += 1
        used_trap = False
        bad_conf = False
        for a in ATTRS:
            g = f.get(a) or {}
            v = g.get("verdict")
            want = it["gold_has_clue"][a]
            r["칸분모"] += 1
            if (v != "abstain") == want:
                r["칸적중"] += 1
            if want:
                r["양성분모"] += 1
                r["양성적중"] += v != "abstain"
            else:
                r["기권분모"] += 1
                r["기권적중"] += v == "abstain"
            c = g.get("confidence")
            if isinstance(c, (int, float)) and not (0 <= c <= 1):
                r["값위반칸"] += 1
                bad_conf = True
            for e in g.get("evidence") or []:
                r["근거분모"] += 1
                s = by_id.get(e)
                if s:
                    r["실재"] += 1
                if s and s["subject"] == "self" and s["_attr"] == a:
                    r["근거적중"] += 1
                if e in trap:
                    used_trap = True
        if used_trap:
            r["함정오용인물"] += 1
            r["함정오용목록"].append(rec["persona_id"])
        if bad_conf:
            r["값위반인물"] += 1
        p = rec.get("probe") or {}
        sk = it.get("scoring_keywords") or {}
        for a in ATTRS:
            if not it["gold_has_clue"][a]:
                continue                      # 단서 없는 칸은 값 적중 분모가 아니다
            kws = [k for k in (sk.get(a) or []) if k]
            if not kws:
                continue                      # 키워드가 없으면 오답으로 세지 않는다
            r["프로브분모"] += 1
            r["프로브적중"] += any(k in str(p.get(a, "")) for k in kws)
    return r


def p(a: int, b: int) -> str:
    return f"{a}/{b} = {a/b:6.1%}" if b else "—"


def main() -> int:
    items = {x["persona_id"]: x for x in
             json.loads((HERE / "input.json").read_text(encoding="utf-8"))}
    rows = {}
    for f in sorted(glob.glob(str(HERE / "results" / "raw_*.json"))):
        tag = Path(f).stem.removeprefix("raw_")
        rows[tag] = score(items, json.loads(Path(f).read_text(encoding="utf-8")))
    if not rows:
        print("결과 파일이 없다")
        return 1

    tags = list(rows)
    w = 26
    def line(label, fn):
        print(f"  {label:<{w}}" + "".join(f"{fn(rows[t]):>20}" for t in tags))

    print("=" * (2 + w + 20 * len(tags)))
    print("2단 모델 크기 측정 — exp05")
    print("=" * (2 + w + 20 * len(tags)))
    print(f"  {'':<{w}}" + "".join(f"{t:>20}" for t in tags))
    print(f"\n  ① 계약 과제")
    line("전체 245칸 정확도", lambda r: p(r["칸적중"], r["칸분모"]))
    line("  양성(단서 있음→발언)", lambda r: p(r["양성적중"], r["양성분모"]))
    line("  음성(단서 없음→기권)", lambda r: p(r["기권적중"], r["기권분모"]))
    print(f"\n  ② 근거 스팬 정확도")
    line("의미상(실재·self·해당속성)", lambda r: p(r["근거적중"], r["근거분모"]))
    line("  실재하는 span_id", lambda r: p(r["실재"], r["근거분모"]))
    line("함정을 근거로 쓴 인물", lambda r: p(r["함정오용인물"], r["함정보유인물"]))
    print(f"\n  ③ 형식 준수율")
    line("구조(JSON 파싱)", lambda r: p(r["구조통과"], r["n"]))
    line("값 제약(confidence 0~1)", lambda r: p(r["n"] - r["값위반인물"], r["n"]))
    print(f"\n  ④ 토큰 · 지연")
    line("편당 출력 토큰", lambda r: f"{r['토큰']/r['n']:.0f}")
    line("편당 지연", lambda r: f"{r['초']/r['n']:.1f}s")
    print(f"\n  참고 — 값 프로브 (부지표)")
    line("scoring_keywords 부분일치", lambda r: p(r["프로브적중"], r["프로브분모"]))
    print()
    for t in tags:
        if rows[t]["함정오용목록"]:
            print(f"  {t} 함정 오용: {', '.join(rows[t]['함정오용목록'][:12])}"
                  + (" …" if len(rows[t]["함정오용목록"]) > 12 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
