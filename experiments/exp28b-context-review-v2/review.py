"""exp28b — exp28 review.py 에서 프롬프트만 v2 로 바꿨다 (README §1). D3(교사 라벨 골드 300편)을 더한다. GPU 서버에서 돈다.

    export PYTHONIOENCODING=utf-8 PYTHONPATH=src
    python experiments/exp28b-context-review-v2/review.py a0 --checkpoint <1단 v2 폴더>                  # D1 · D2 · D3 의 1단 결과
    python experiments/exp28b-context-review-v2/review.py llm --mode A --model <Qwen 폴더> --tag 4b      # D1 (글 하나씩 · 시간 잼)
    python experiments/exp28b-context-review-v2/review.py llm --mode A --model <Qwen 폴더> --tag 4b --set d3  # D3 (묶어서)

출력: results/a0_{d1|d2|d3}.jsonl · {A|B}_{tag}_{d1|d2|d3}.jsonl — 글마다 {post_id, spans:[{start,end,text,type,subject}], raw, sec}
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

TYPES = """(label-schema §3-2 — 무엇을 잡나 · 예)
- AGE: 나이 · 연령대 신호 (마흔여덟 / 서른넷 / 90년생)
- SEX: 성별 신호 (아내가 / 남편이 / 와이프)
- LOC_ADMIN: 행정구역명 (성수동 / 용인 / 기흥)
- LOC_FACILITY: 시설 · 랜드마크 · 상호 (신갈저수지 / 서울숲 / 성수역)
- REL_HOME: 거주 관계어 (집 근처 / 집 앞 / 동네 / 우리 동네)
- REL_WORK: 직장 관계어 (회사 앞 / 사무실 근처 / 공장에서)
- JOB: 직업 · 직무 · 업종 (생산관리 / 완성차 공장 / 카페 매니저)
- FAM: 가족 구성 · 생애단계 (첫째가 고등학교 배정 / 손주 돌잔치)
- COMMUTE: 교통수단 · 노선 · 통근 패턴 · 통근 관계어 (2호선 / 자차 출퇴근 / 퇴근길)
- INCOME: 소비 · 지출 수준 신호 (장비 값 / 회비 / 등급제)
- BIRTHDAY: 글쓴이 생일 날짜
- PET_NAME: 글쓴이가 키우는 동물의 이름"""

RULES = """단서의 정의 (label-schema §4-1 — 세 등급 모두 단서다):
- explicit: 값이 그대로 적힘 (마흔여덟 / 2호선)
- implicit: 값이 직접 안 적혔으나 문맥상 거의 확정 (완성차 공장 출장 / 원두 발주)
- inferential: 단독으로는 미확정이지만 다른 단서와 묶이면 좁혀짐 (신갈저수지 / 집 근처)
→ 값이 직접 적히지 않은 간접적인 말도 위 범주를 드러내면 단서다

subject — 누구의 정보인가 (§4-2 · 그 스팬이 속한 문장만 보고 정한다):
- self = 글쓴이 자신의 정보 · other = 다른 사람(가족 · 친구 · 지인 · 등장인물)의 정보 · unknown = 문장만으로 알 수 없음 (예: 여행으로 잠깐 간 곳)
- 다른 사람의 정보는 버리지 않고 subject 를 other 로 바꾼다

버리기(drop)는 좁게 — 후보는 탐지기가 이미 단서로 본 것이다. 그 말이 글쓴이 · 다른 사람 **누구에 대해서도** 위 범주를 드러내지 않을 때만 버린다:
- 유행어 · 평가말 · 농담처럼 쓰인 말 / 드라마 · 영화 · 뉴스 등 매체 속 장소 / 고유명사가 아닌 일반어가 장소로 잡힌 것
- 애매하면 버리지 않는다

문자열은 글에 나온 그대로 쓴다 (고치거나 줄이지 않는다)"""

SYSTEM = "너는 한국어 SNS 글에서 글쓴이를 특정할 수 있는 개인 단서를 찾는 검토자다. 반드시 JSON 하나만 출력한다."


def prompt_a(body: str, spans: list[dict]) -> str:
    listed = "\n".join(f"{i}. 「{s['text']}」 {s['type']} {s['subject']}" for i, s in enumerate(spans, 1)) or "(없음)"
    return (f"단서 유형:\n{TYPES}\n\n{RULES}\n\n[글]\n{body}\n\n[자동 탐지기가 찾은 단서 후보]\n{listed}\n\n"
            "할 일: ① 후보 중 위 기준으로 확실히 단서가 아닌 것의 번호만 drop 에 ② subject 가 틀린 후보는 subject 에 바른 값을 "
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


def load_d3() -> list[dict]:
    want = set(json.load(open(HERE / "data" / "d3_post_ids.json", encoding="utf-8"))["post_ids"])
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data/corpus/v0/gold/*_spans.jsonl"))):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            if d.get("post_id") in want:
                rows.append({"post_id": d["post_id"], "body": d["texts"]["body"]})
    assert len(rows) == 300
    return rows


def run_a0(a) -> None:
    import c1_rules
    import infer
    from kopl.c1_span.attributes import resolve

    det = infer.SpanDetector(a.checkpoint, device="cuda", min_span_score=0.7)
    for name in a.sets.split(","):
        rows = {"d1": load_d1, "d2": load_d2, "d3": load_d3}[name]()
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
    name = a.set
    rows = {"d1": load_d1, "d2": load_d2, "d3": load_d3}[name]()
    a0 = {json.loads(l)["post_id"]: json.loads(l)["spans"] for l in open(HERE / "results" / f"a0_{name}.jsonl", encoding="utf-8")}
    llm = LLM(a.model)
    out = HERE / "results" / f"{a.mode}_{a.tag}_{name}.jsonl"
    bs = 1 if name == "d1" else a.batch
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
    p0.add_argument("--sets", default="d1,d2,d3")
    p1 = sub.add_parser("llm")
    p1.add_argument("--mode", choices=["A", "B"], required=True)
    p1.add_argument("--model", required=True)
    p1.add_argument("--tag", required=True)
    p1.add_argument("--set", choices=["d1", "d2", "d3"], default="d1")
    p1.add_argument("--batch", type=int, default=8)
    a = ap.parse_args()
    (HERE / "results").mkdir(exist_ok=True)
    run_a0(a) if a.cmd == "a0" else run_llm(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
