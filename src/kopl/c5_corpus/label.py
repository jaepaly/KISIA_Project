"""교사 LLM 자동라벨 — 글에서 스팬을 뽑아 골드셋을 만든다.

    python label.py --posts data/corpus/v0/posts --out data/corpus/v0/gold \\
        --provider anthropic --model claude-sonnet-4-6

    python label.py ... --design      설계본. clue_plan 을 힌트로 준다

⚠️ **두 벌을 만든다.**

  탐지본 (기본)   글만 준다        교사가 실제로 무엇을 찾는가
  설계본 (--design) 글 + clue_plan  설계 정답에 가까운 라벨

**둘의 차이가 「교사가 놓치는 것」이다.** B 의 1단이 그걸 학습 타깃으로 쓰고,
C 의 blind 200 과 대조할 때도 탐지본이어야 의미가 있다 — 설계본은 답을 보고 쓴 것이다.

⚠️ **교사 모델은 생성 모델과 계열이 달라야 한다.**
같은 계열이면 자기가 심은 걸 자기가 회수해서 「추가 탐지율」이 무의미해진다.
코퍼스의 `gen_model` 을 읽어 같은 계열이면 실행을 막는다.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

try:
    from . import label_prompts
    from .llm import LLMClient, LLMError, load_dotenv
except ImportError:      # python label.py 로 직접 실행할 때
    import label_prompts
    from llm import LLMClient, LLMError, load_dotenv

SCHEMA_VERSION = "1.0"
TEXT_ID_RE = re.compile(r"^(title|body|profile_bio|photo_caption:\d+)$")
FIELDS = ("span_id", "text_id", "start", "end", "text", "type", "level", "subject")

# 계열 판정용. gen_model 문자열과 교사 모델 문자열에서 이 조각을 찾는다
FAMILIES = ("claude", "anthropic", "gpt", "openai", "codex", "gemini", "qwen", "llama")


def family(model: str) -> str | None:
    m = str(model).lower()
    for f in FAMILIES:
        if f in m:
            return {"anthropic": "claude", "openai": "gpt", "codex": "gpt"}.get(f, f)
    return None


def texts_of(rec: dict) -> dict:
    """글 레코드에서 채널별 텍스트를 꺼낸다.

    #134 이후는 `texts` 객체 하나로 온다. 그 이전 형식은 `title`·`body` 가
    최상위에 있고 캡션이 `photo_captions` 에 따로 있다.
    **폴백에서 캡션을 빠뜨리면 설계 단서 40건이 교사 라벨에 안 붙는다** —
    그러면 검수 골드셋에도 못 들어가고 그 채널이 통째로 측정에서 빠진다.
    화요일 생성에 #134 이전 글이 섞일 수 있어 둘 다 읽는다.
    """
    t = rec.get("texts")
    if isinstance(t, dict) and t:
        out = dict(t)
    else:
        out = {k: rec[k] for k in ("title", "body") if rec.get(k)}
        caps = rec.get("photo_captions") or {}
        if isinstance(caps, dict):
            for k, v in caps.items():
                # 키가 이미 photo_caption:N 이면 그대로, 숫자만 오면 붙인다
                key = k if str(k).startswith("photo_caption") else f"photo_caption:{k}"
                if v:
                    out[key] = v
        elif isinstance(caps, list):
            for i, v in enumerate(caps):
                if v:
                    out[f"photo_caption:{i}"] = v
    return {k: unicodedata.normalize("NFC", v) for k, v in out.items() if v}


def parse_spans(raw: str) -> list[dict]:
    """모델 응답에서 JSON 배열만 건진다. 코드펜스나 머리말이 섞여도 잡는다."""
    t = raw.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("["), t.rfind("]")
    if i < 0 or j < i:
        return []
    try:
        out = json.loads(t[i:j + 1])
    except Exception:  # noqa: BLE001
        return []
    return [x for x in out if isinstance(x, dict)]


def locate(spans: list[dict], texts: dict) -> tuple[list[dict], list[str]]:
    """모델이 고른 표현의 위치를 코드가 찾는다.

    같은 표현이 여러 번 나오면 아직 안 쓴 자리를 앞에서부터 잡는다.
    원문에 없으면 버린다 — 모델이 표현을 바꿔 적은 것이라 신뢰할 수 없다.

    ⚠️ 자리 선점은 **똑같은 문자열끼리만** 따진다.
    길이가 다른 표현끼리의 겹침은 여기서 거르면 안 된다 — dedupe 가 최장 우선으로
    푸는데 그 전에 긴 쪽이 사라진다.
    """
    ok, dropped = [], []
    taken: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for sp in spans:
        tid = str(sp.get("text_id", "body"))
        txt = unicodedata.normalize("NFC", str(sp.get("text", "")))
        if tid not in texts or not txt:
            dropped.append(f"{tid}:{txt[:20]} (채널 없음)")
            continue
        hay = texts[tid]
        used = taken.setdefault((tid, txt), [])
        pos, found = 0, None
        while True:
            k = hay.find(txt, pos)
            if k < 0:
                break
            if not any(k < e and s < k + len(txt) for s, e in used):
                found = k
                break
            pos = k + 1
        if found is None:
            dropped.append(f"{tid}:{txt[:20]} (원문에 없음)")
            continue
        used.append((found, found + len(txt)))
        ok.append({**sp, "text_id": tid, "text": txt,
                   "start": found, "end": found + len(txt)})
    return ok, dropped


def dedupe(spans: list[dict]) -> tuple[list[dict], list[str]]:
    """겹치는 스팬을 없앤다 — 최장 우선 (label-schema §6).

    BIO 태깅이 토큰 하나에 라벨 하나만 붙일 수 있어 겹침을 표현하지 못한다.
    겹침 판정은 **같은 text_id 안에서만** 한다.

    ⚠️ **최장 우선이 모델 오류를 증폭한다.**
    §6 이 든 예시의 정답은 「집 근처」+「신갈저수지」 **두 개**인데,
    모델이 「집 근처라 자주 가는 신갈저수지」를 하나로 내면 최장 우선이
    멀쩡한 둘을 잡아먹는다. 계약을 어길 수 없으니 **삼킨 횟수를 경고로 낸다** —
    잦으면 프롬프트의 겹침 지시를 세게 써야 한다는 뜻이다.
    """
    out: list[dict] = []
    warn: list[str] = []
    for sp in sorted(spans, key=lambda x: (x["end"] - x["start"]), reverse=True):
        hit = [o for o in out if o["text_id"] == sp["text_id"]
               and sp["start"] < o["end"] and o["start"] < sp["end"]]
        if hit:
            continue
        out.append(sp)
    # 긴 스팬 하나가 짧은 것 둘 이상을 덮었는지 본다
    for o in out:
        eaten = [s for s in spans if s is not o and s["text_id"] == o["text_id"]
                 and o["start"] <= s["start"] and s["end"] <= o["end"]]
        if eaten:
            # 1건 삼킴도 손실이다. §6 의 예시가 2개라 문턱을 2로 뒀었는데,
            # 짧은 스팬 하나를 잃는 것도 그 채널에서 단서가 사라지는 것이다
            warn.append(f"「{o['text'][:24]}」 가 짧은 스팬 {len(eaten)}개를 덮었다")
    return sorted(out, key=lambda x: (x["text_id"], x["start"])), warn


def finalize(spans: list[dict], post_id: str, texts: dict) -> tuple[list[dict], list[str]]:
    """span_id 를 붙이고 계약 검사를 건다 (§11)."""
    order = {"title": 0, "body": 1, "profile_bio": 3}
    def key(s):
        t = s["text_id"]
        return (2, int(t.split(":")[1])) if t.startswith("photo_caption") else (order[t], 0)

    out, bad = [], []
    for i, sp in enumerate(sorted(spans, key=lambda s: (key(s), s["start"])), 1):
        if sp.get("type") not in label_prompts.TYPES:
            bad.append(f"type={sp.get('type')}"); continue
        if sp.get("level") not in label_prompts.LEVELS:
            bad.append(f"level={sp.get('level')}"); continue
        if sp.get("subject") not in label_prompts.SUBJECTS:
            sp["subject"] = "self"
        if not TEXT_ID_RE.match(sp["text_id"]):
            bad.append(f"text_id={sp['text_id']}"); continue
        if sp["text"] != texts[sp["text_id"]][sp["start"]:sp["end"]]:
            bad.append(f"offset 불일치 {sp['text']}"); continue
        out.append({"span_id": f"{post_id}_s{i:02d}", **{k: sp[k] for k in FIELDS[1:]}})
    return out, bad


def label_one(client: LLMClient, texts: dict, hint=None) -> tuple[list[dict], list[str]]:
    raw = client.complete(label_prompts.SYSTEM, label_prompts.build_user(texts, hint))
    return locate(dedupe_input(parse_spans(raw)), texts)


def dedupe_input(spans: list[dict]) -> list[dict]:
    """모델이 같은 것을 두 번 낸 경우를 접는다."""
    seen, out = set(), []
    for s in spans:
        k = (s.get("text_id"), s.get("text"), s.get("type"))
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", default="data/corpus/v0/posts")
    ap.add_argument("--personas", default="data/corpus/v0/personas")
    ap.add_argument("--out", default="data/corpus/v0/gold")
    ap.add_argument("--provider", default="anthropic")
    ap.add_argument("--model", default=None)
    ap.add_argument("--design", action="store_true",
                    help="clue_plan 을 힌트로 준다. 기본은 탐지본이다")
    ap.add_argument("--limit", type=int, default=0, help="인물당 n편만")
    ap.add_argument("--sleep", type=float, default=0.0)
    a = ap.parse_args()

    load_dotenv()
    client = LLMClient(a.provider, a.model)
    teacher_fam = family(client.model)

    out_dir = Path(a.out) / ("design" if a.design else "detect")
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.design:
        print("⚠️ 설계본 — clue_plan 을 힌트로 준다. 탐지력 측정에는 쓸 수 없다\n")

    files = sorted(glob.glob(str(Path(a.posts) / "*.jsonl")))
    if not files:
        print(f"글을 못 찾았다: {a.posts}")
        return 1

    tot_spans = tot_posts = 0
    all_dropped: list[str] = []
    all_swallow: list[str] = []

    for f in files:
        pid = Path(f).stem
        recs = [json.loads(l) for l in Path(f).read_text(encoding="utf-8-sig").splitlines()
                if l.strip()]
        if not recs:
            continue

        # 순환 편향 차단 — 한 파일 안에 gen_model 이 섞일 수 있으므로 전량을 본다.
        # 생성이 끊겨 다시 돌릴 때 provider 를 바꿨거나, 한도에 걸려 경로를 바꿨을 수 있다.
        # 「생성·교사·교차모델·2단이 전부 다른 계열」이 이 프로젝트의 대표 논거라
        # 첫 줄만 보고 판정하면 약하다.
        gens = {family(r.get("gen_model", "")) for r in recs} - {None}
        if teacher_fam and teacher_fam in gens:
            models = sorted({r.get("gen_model", "") for r in recs
                             if family(r.get("gen_model", "")) == teacher_fam})
            print(f"✗ 순환 편향: 생성에 {', '.join(models)} 이(가) 섞여 있는데 "
                  f"교사도 {teacher_fam} 계열이다.\n"
                  f"    자기가 심은 것을 자기가 회수하면 「추가 탐지율」이 무의미해진다.")
            return 2
        if len(gens) > 1:
            print(f"  ⚠ 생성 계열이 섞여 있다: {sorted(gens)} — provenance 에 남는다")

        hints: dict[str, list] = {}
        if a.design:
            pf = Path(a.personas) / f"{pid}.json"
            if pf.is_file():
                for c in json.loads(pf.read_text(encoding="utf-8-sig")).get("clue_plan", []):
                    if c.get("post"):
                        hints.setdefault(c["post"], []).append(c)

        if a.limit:
            recs = recs[:a.limit]
        rows: list[dict] = []
        print(f"■ {pid}  {len(recs)}편")

        for n, r in enumerate(recs):
            texts = texts_of(r)
            if not texts:
                continue
            if a.sleep and n:
                time.sleep(a.sleep)
            post = str(r["post_id"]).rsplit("_", 1)[-1]
            try:
                found, dropped = label_one(client, texts, hints.get(post))
            except LLMError as e:
                print(f"  ✗ {r['post_id']} 실패: {e}")
                continue
            kept, swallow = dedupe(found)
            spans, bad = finalize(kept, r["post_id"], texts)
            all_dropped += [f"{r['post_id']} {d}" for d in dropped + bad]
            all_swallow += [f"{r['post_id']} {w}" for w in swallow]
            rows.append({"post_id": r["post_id"], "persona_id": r.get("persona_id", pid),
                         "texts": texts, "spans": spans,
                         "flags": {"gen_signal": False, "meme_hits": [],
                                   "negative_control": bool(r.get("negative_control"))},
                         "reviewed": False})
            tot_spans += len(spans)
            print(f"  {r['post_id']}  스팬 {len(spans):2}건"
                  + (f"  (버림 {len(dropped) + len(bad)})" if dropped or bad else ""))

        # profile_bio 는 사용자 단위다 (§8-4). 글 레코드에 넣지 않는다
        prof = Path(a.posts) / f"{pid}_profile.json"
        user_rec = None
        if prof.is_file():
            pj = json.loads(prof.read_text(encoding="utf-8-sig"))
            ptexts = {k: unicodedata.normalize("NFC", v)
                      for k, v in (pj.get("texts") or {}).items() if v}
            if ptexts:
                try:
                    found, _ = label_one(client, ptexts,
                                         [pj["clue"]] if a.design and pj.get("clue") else None)
                    kept, _ = dedupe(found)
                    sp, _ = finalize(kept, f"{pid}_bio", ptexts)
                    user_rec = {"persona_id": pid, "profile_bio": ptexts["profile_bio"],
                                "spans": sp, "reviewed": False}
                    tot_spans += len(sp)
                    print(f"  {pid}_bio  스팬 {len(sp)}건 (사용자 단위)")
                except LLMError as e:
                    print(f"  ✗ 프로필 실패: {e}")

        header = {"schema_version": SCHEMA_VERSION, "corpus_version": "v0",
                  "teacher_model": client.version,
                  "label_prompt_version": label_prompts.LABEL_PROMPT_VERSION,
                  "mode": "design" if a.design else "detect"}
        lines = [json.dumps(header, ensure_ascii=False)]
        if user_rec:
            lines.append(json.dumps(user_rec, ensure_ascii=False))
        lines += [json.dumps(r, ensure_ascii=False) for r in rows]
        (out_dir / f"{pid}_spans.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        tot_posts += len(rows)

    print("\n" + "=" * 60)
    print(f"글 {tot_posts}편 · 스팬 {tot_spans}건 · {client.version}")
    print(f"출력 {out_dir}")
    if all_dropped:
        print(f"\n버린 스팬 {len(all_dropped)}건 — 원문에 없거나 계약을 어겼다")
        for d in all_dropped[:8]:
            print(f"  {d}")
        if len(all_dropped) > 8:
            print(f"  … 외 {len(all_dropped) - 8}건")
    if all_swallow:
        print(f"\n⚠️ 최장 우선이 짧은 스팬을 삼킨 경우 {len(all_swallow)}건")
        print("   §6 의 정답은 나누는 쪽이다. 잦으면 겹침 지시를 세게 써야 한다")
        for w in all_swallow[:5]:
            print(f"  {w}")

    print(f"\n[한도] {client.burn_report(tot_posts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
