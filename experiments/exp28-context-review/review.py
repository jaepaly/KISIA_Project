"""exp28 — 1단(A0)과 큰 모델 보정(A) · 대체(B)를 돌려 예측을 남긴다 (README §2). GPU 서버에서 돈다.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/exp28-context-review/review.py a0 --checkpoint <1단 v2 폴더>                  # D1 · D2 의 1단 결과
    python experiments/exp28-context-review/review.py llm --mode A --model <Qwen 폴더> --tag 4b      # D1 (글 하나씩 · 시간 잼)
    python experiments/exp28-context-review/review.py llm --mode A --model <Qwen 폴더> --tag 4b --d2 # D2 (묶어서)

출력: results/a0_d1.jsonl · a0_d2.jsonl · {A|B}_{tag}_{d1|d2}.jsonl — 글마다 {post_id, spans:[{start,end,text,type,subject}], raw, sec}
프롬프트 해시는 결과 첫 줄 `meta` 에 적는다. A · B 의 프롬프트는 모델 크기와 관계없이 같다.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "src", ROOT / "experiments" / "exp06-finetune", ROOT / "apps" / "analyzer" / "engines"):
    sys.path.insert(0, str(p))

CONTRACT = ["AGE", "SEX", "LOC_ADMIN", "LOC_FACILITY", "REL_HOME", "REL_WORK", "JOB", "FAM", "COMMUTE", "INCOME"]
EXTRA = ["BIRTHDAY", "PET_NAME"]
SUBJECTS = {"self", "other", "unknown"}

TYPES = """- AGE: 나이 · 연령대 (서른넷 · 90년생 · 사십대)
- SEX: 글쓴이 성별을 드러내는 말 (아내가 · 남편이 · 와이프)
- LOC_ADMIN: 행정구역 이름 (성수동 · 용인)
- LOC_FACILITY: 시설 · 랜드마크 · 가게 이름 (서울숲 · 성수역 · 가게 상호)
- REL_HOME: 사는 곳과의 관계를 드러내는 말 (집 근처 · 우리 동네)
- REL_WORK: 일터와의 관계를 드러내는 말 (회사 앞 · 사무실 근처)
- JOB: 직업 · 직무 · 업종 (생산관리 · 카페 매니저 · 회사원임을 드러내는 말)
- FAM: 가족 구성 · 생애 단계 (첫째가 고등학생 · 손주 돌잔치 · 신혼)
- COMMUTE: 교통수단 · 노선 · 통근 (2호선 · 자차 출퇴근 · 퇴근길)
- INCOME: 소비 · 지출 수준 (장비 값 · 회비)
- BIRTHDAY: 글쓴이 생일 날짜
- PET_NAME: 글쓴이가 키우는 동물의 이름"""

RULES = """판단 기준:
- 단서는 「이 글을 쓴 사람이 누구인지 좁히는 데 쓰일 수 있는 말」이다. 글 전체 문맥을 보고 판단한다
- subject: self = 글쓴이 자신의 정보 · other = 다른 사람(가족 · 친구 · 지인 · 등장인물)의 정보 · unknown = 글쓴이 정보인지 알 수 없음 (예: 여행으로 잠깐 간 곳)
- 단서가 아닌 것: 유행어 · 평가말 · 농담처럼 쓰인 말 / 드라마 · 영화 · 뉴스 등 매체 속 장소 / 글쓴이 성별과 관계없는 호칭(부모 · 지인을 부르는 말)
- 문자열은 글에 나온 그대로 쓴다 (고치거나 줄이지 않는다)"""

SYSTEM = "너는 한국어 SNS 글에서 글쓴이를 특정할 수 있는 개인 단서를 찾는 검토자다. 반드시 JSON 하나만 출력한다."


def prompt_a(body: str, spans: list[dict]) -> str:
    listed = "\n".join(f"{i}. 「{s['text']}」 {s['type']} {s['subject']}" for i, s in enumerate(spans, 1)) or "(없음)"
    return (f"단서 유형:\n{TYPES}\n\n{RULES}\n\n[글]\n{body}\n\n[자동 탐지기가 찾은 단서 후보]\n{listed}\n\n"
            "할 일: ① 후보 중 단서가 아닌 것의 번호를 drop 에 ② subject 가 틀린 후보는 subject 에 바른 값을 "
            "③ 탐지기가 놓친 단서는 add 에 넣어라. 바꿀 것이 없으면 빈 값으로 둔다.\n"
            '출력 형식: {"drop": [번호], "subject": {"번호": "self|other|unknown"}, "add": [{"text": "글에 있는 그대로", "type": "유형", "subject": "self|other|unknown"}]}')


def prompt_b(body: str) -> str:
    return (f"단서 유형:\n{TYPES}\n\n{RULES}\n\n[글]\n{body}\n\n"
            "할 일: 글에 있는 단서를 모두 찾아라. 없으면 빈 목록.\n"
            '출력 형식: {"spans": [{"text": "글에 있는 그대로", "type": "유형", "subject": "self|other|unknown"}]}')


PROMPT_HASH = hashlib.sha256((SYSTEM + TYPES + RULES + prompt_a("X", []) + prompt_b("X")).encode()).hexdigest()[:12]


def parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


def occurrences(body: str, text: str) -> list[tuple[int, int]]:
    if not isinstance(text, str) or not text.strip():
        return []
    out, at = [], body.find(text)
    while at >= 0:
        out.append((at, at + len(text)))
        at = body.find(text, at + 1)
    return out


def overlaps(a: tuple[int, int], spans: list[dict]) -> bool:
    return any(s["start"] < a[1] and a[0] < s["end"] for s in spans)


def load_d1() -> list[dict]:
    rows = [json.loads(l) for l in open(HERE / "data" / "posts.jsonl", encoding="utf-8")]
    return [{"post_id": r["post_id"], "body": r["texts"]["body"]} for r in rows if not r.get("excluded")]


def load_d2() -> list[dict]:
    test = set(json.load(open(ROOT / "data/corpus/v0/splits/test_post_ids.json", encoding="utf-8"))["post_ids"])
    assert len(test) == 255
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("reviewed") and "spans" in d and d["post_id"] not in test and d["texts"].get("body"):
                rows.append({"post_id": d["post_id"], "body": d["texts"]["body"]})
    return rows


def run_a0(a) -> None:
    import c1_rules
    import infer
    from kopl.c1_span.attributes import resolve

    det = infer.SpanDetector(a.checkpoint, device="cuda", min_span_score=0.7)
    for name, rows in (("d1", load_d1()), ("d2", load_d2())):
        with open(HERE / "results" / f"a0_{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                t = time.perf_counter()
                spans = c1_rules.detect(det, {"post_id": r["post_id"], "body": r["body"]}, resolve)["spans"]
                spans = [{k: s[k] for k in ("start", "end", "text", "type", "subject")} for s in spans if s["text_id"] == "body"]
                f.write(json.dumps({"post_id": r["post_id"], "spans": spans, "sec": round(time.perf_counter() - t, 3)}, ensure_ascii=False) + "\n")
        print(name, len(rows), flush=True)


class LLM:
    def __init__(self, path: str):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        self.tok.padding_side = "left"
        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
        self.model = AutoModelForCausalLM.from_pretrained(path, quantization_config=q, device_map="cuda:0", dtype=torch.bfloat16).eval()

    def generate(self, users: list[str], max_new: int = 768) -> list[str]:
        texts = [self.tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": u}],
                                              tokenize=False, add_generation_prompt=True, enable_thinking=False) for u in users]
        enc = self.tok(texts, return_tensors="pt", padding=True).to("cuda:0")
        with self.torch.no_grad():
            out = self.model.generate(**enc, max_new_tokens=max_new, do_sample=False, temperature=None, top_p=None, top_k=None,
                                      pad_token_id=self.tok.pad_token_id)
        return [self.tok.decode(o[enc["input_ids"].shape[1]:], skip_special_tokens=True) for o in out]


def apply_a(body: str, spans: list[dict], v: dict | None) -> list[dict]:
    if v is None:
        return spans
    drop = {d for d in v.get("drop") or [] if isinstance(d, int)}
    subj = v.get("subject") if isinstance(v.get("subject"), dict) else {}
    kept = []
    for i, s in enumerate(spans, 1):
        if i in drop:
            continue
        new = subj.get(str(i), subj.get(i))
        kept.append({**s, "subject": new} if new in SUBJECTS else dict(s))
    for x in v.get("add") or []:
        if not isinstance(x, dict) or x.get("type") not in CONTRACT + EXTRA:
            continue
        for st, en in occurrences(body, x.get("text")):
            if not overlaps((st, en), kept):
                kept.append({"start": st, "end": en, "text": x["text"], "type": x["type"],
                             "subject": x.get("subject") if x.get("subject") in SUBJECTS else "self", "added": True})
    return sorted(kept, key=lambda s: s["start"])


def apply_b(post_id: str, body: str, v: dict | None, rules_mod, explicit, resolve) -> list[dict]:
    llm_spans = {}
    for x in (v or {}).get("spans") or []:
        if not isinstance(x, dict) or x.get("type") not in CONTRACT + EXTRA:
            continue
        for st, en in occurrences(body, x.get("text")):
            llm_spans.setdefault((st, en, x["type"]), x.get("subject") if x.get("subject") in SUBJECTS else "self")
    cands = [{"text_id": "body", "start": st, "end": en, "type": t, "text": body[st:en], "score": 1.0, "span_id": f"{post_id}_s{i:02d}"}
             for i, ((st, en, t), _) in enumerate(sorted((k, s) for k, s in llm_spans.items() if k[2] in CONTRACT), 1)]
    merged, _ = rules_mod.merge_with_model(post_id, {"body": body}, cands, explicit)
    out = []
    for c in merged:
        key = (c["start"], c["end"], c["type"])
        subject = llm_spans[key] if key in llm_spans else resolve({"body": body}, dict(c))["subject"]
        out.append({"start": c["start"], "end": c["end"], "text": c["text"], "type": c["type"], "subject": subject, "from_llm": key in llm_spans})
    for (st, en, t), s in sorted(llm_spans.items()):
        if t in EXTRA and not overlaps((st, en), out):
            out.append({"start": st, "end": en, "text": body[st:en], "type": t, "subject": s, "from_llm": True})
    return sorted(out, key=lambda s: s["start"])


def run_llm(a) -> None:
    from kopl.c1_span import rules as rules_mod
    from kopl.c1_span.attributes import resolve

    explicit = rules_mod.ExplicitRules()
    name = "d2" if a.d2 else "d1"
    rows = load_d2() if a.d2 else load_d1()
    a0 = {json.loads(l)["post_id"]: json.loads(l)["spans"] for l in open(HERE / "results" / f"a0_{name}.jsonl", encoding="utf-8")}
    llm = LLM(a.model)
    out = HERE / "results" / f"{a.mode}_{a.tag}_{name}.jsonl"
    bs = a.batch if a.d2 else 1
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"meta": {"mode": a.mode, "model": a.model, "prompt_hash": PROMPT_HASH, "batch": bs}}, ensure_ascii=False) + "\n")
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            users = [prompt_a(r["body"], a0[r["post_id"]]) if a.mode == "A" else prompt_b(r["body"]) for r in chunk]
            t = time.perf_counter()
            raws = llm.generate(users)
            sec = (time.perf_counter() - t) / len(chunk)
            for r, raw in zip(chunk, raws):
                v = parse(raw)
                spans = apply_a(r["body"], a0[r["post_id"]], v) if a.mode == "A" else apply_b(r["post_id"], r["body"], v, rules_mod, explicit, resolve)
                f.write(json.dumps({"post_id": r["post_id"], "spans": spans, "parsed": v is not None, "raw": raw, "sec": round(sec, 3)}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{i + len(chunk)}/{len(rows)} {sec:.1f}s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p0 = sub.add_parser("a0")
    p0.add_argument("--checkpoint", required=True)
    p1 = sub.add_parser("llm")
    p1.add_argument("--mode", choices=["A", "B"], required=True)
    p1.add_argument("--model", required=True)
    p1.add_argument("--tag", required=True)
    p1.add_argument("--d2", action="store_true")
    p1.add_argument("--batch", type=int, default=8)
    a = ap.parse_args()
    (HERE / "results").mkdir(exist_ok=True)
    run_a0(a) if a.cmd == "a0" else run_llm(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
