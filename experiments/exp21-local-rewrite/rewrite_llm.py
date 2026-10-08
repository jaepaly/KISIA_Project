"""로컬 Qwen3-4B(어댑터 끔)로 단서 구간 바꿔 쓰기 후보를 만든다 — 규칙 엔진(rewrite.py)이 못 내는 직업·장소·집 근처 단서용.

글은 밖으로 나가지 않는다 — 2단 모델과 같은 GPU 모델을 쓰고, 어댑터만 잠깐 끈다(PeftModel.disable_adapter).
2단 판정 모델에는 원문을 보내지 않지만(계약 설계 제약 5), 바꿔 쓰기는 문맥이 있어야 해서 원문 글을 로컬 모델에 준다.

v1 (v0 시제품 결과 반영):
- 모델은 **조사를 뗀 핵심어만** 바꾼다 → 조사는 josa.replace 가 받침에 맞춰 다시 붙인다 (v0: 「세 살 아이는 → 아이」 조사 빠짐)
- 거름: 원래 핵심어를 그대로 품음(「탄천 → 탄천 지역」) · 앞뒤 말과 겹침(「공연장 주변 + 근처」) · 조사를 맞출 수 없음
- 1단 재탐지(잔존)는 호출부가 detector 를 넘기면 거른다
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from kopl.c4_stage2 import josa

TYPE_KO = {
    "AGE": "나이", "SEX": "성별", "LOC_ADMIN": "지역", "LOC_FACILITY": "장소", "REL_HOME": "집 근처", "REL_WORK": "직장 관련",
    "JOB": "직업", "FAM": "가족", "COMMUTE": "통근", "INCOME": "소득",
}

SYSTEM = """너는 블로그 글의 개인정보 노출을 줄이는 편집자다.
표시한 말들은 글쓴이를 특정하는 단서(직업·장소·사는 곳·가족 등)다. 각 말을 대신할 **더 일반적인 말**을 제안한다.

규칙:
- 같은 종류의 더 넓은 말(상위어)로만 바꾼다: 「울산박물관」→「박물관」, 「감귤밭」→「밭」, 「정근수당」→「수당」
- 원래 말을 그대로 품으면 안 된다: 「탄천」→「탄천 근처」 ✗ → 「근처 하천」 ○
- 다른 종류의 말로 바꾸지 않는다: 「구청」→「지방청」 ✗, 「샵」→「온라인 쇼핑몰」 ✗ → 「가게」 ○
- 원래 없던 정보를 만들지 않는다. 조사는 붙이지 않는다 (조사는 따로 맞춘다)
- 앞뒤 문장에 그대로 끼워 넣었을 때 자연스러워야 한다. 앞뒤 말과 같은 말이 겹치면 안 된다
- 더 일반적인 말이 없거나 자연스럽지 않으면 null
출력은 JSON 객체 하나: {"1": "바꾼 말", "2": null, ...}. 설명은 쓰지 않는다."""

FEW_SHOT_USER = """글:
퇴근하고 편의점 알바 언니랑 수다 떨다가 집에 왔다. 오늘도 계산대 앞에서 발이 퉁퉁 부었다. 내일은 울산박물관 앞 공원에서 엄마를 만나기로 했다.

바꿀 말:
1. 「편의점 알바 언니」 (직업) — 문맥: 퇴근하고 「편의점 알바 언니」랑 수다 떨다가
2. 「계산대」 (직업) — 문맥: 오늘도 「계산대」 앞에서 발이
3. 「울산박물관」 (장소) — 문맥: 내일은 「울산박물관」 앞 공원에서
4. 「엄마」 (가족) — 문맥: 공원에서 「엄마」를 만나기로"""
FEW_SHOT_ASSISTANT = """{"1": "같이 일하는 언니", "2": "일하는 자리", "3": "박물관", "4": null}"""

_NEIGHBOR_WORDS = {"근처", "주변", "쪽", "앞", "옆", "뒤", "인근", "지역", "부근"}


def _first_word(s: str) -> str:
    m = re.match(r"\s*([가-힣A-Za-z0-9]+)", s)
    return m.group(1) if m else ""


def _last_word(s: str) -> str:
    m = re.search(r"([가-힣A-Za-z0-9]+)\s*$", s)
    return m.group(1) if m else ""


def build_messages(text: str, items: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    lines = []
    for i, it in enumerate(items, 1):
        ctx = f"{it['before'][-15:]}「{it['core']}」{it['after_core'][:12]}".replace("\n", " ")
        lines.append(f"{i}. 「{it['core']}」 ({TYPE_KO.get(it['type'], it['type'])}) — 문맥: {ctx.strip()}")
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": FEW_SHOT_USER},
        {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
        {"role": "user", "content": f"글:\n{text}\n\n바꿀 말:\n" + "\n".join(lines)},
    ]


def _check(item: Mapping[str, Any], new_core: Any) -> tuple[str | None, str]:
    """(바꾼 스팬 문자열 | None, 거른 이유)"""
    if not isinstance(new_core, str):
        return None, "null"
    v = new_core.strip().strip("「」\"'")
    core = item["core"]
    if not v or v == core or "\n" in v or len(v) > len(core) + 12:
        return None, "형식"
    if core in v:
        return None, "원래 말을 품음"
    last, first = _last_word(v), _first_word(v)
    nxt, prv = _first_word(item["after_core"]), _last_word(item["before"])
    if (last in _NEIGHBOR_WORDS and nxt in _NEIGHBOR_WORDS) or (nxt and last == nxt) or (prv and first == prv):
        return None, "앞뒤 말과 겹침"
    loc = item["type"] in ("LOC_ADMIN", "LOC_FACILITY", "REL_HOME", "REL_WORK")
    out = josa.replace(item["text"], v, item["after"], loc=loc)
    if out is None:
        return None, "조사를 맞출 수 없음"
    return out, ""


def make_items(text: str, spans: Sequence[Mapping[str, Any]], *, max_spans: int = 8) -> list[dict[str, Any]]:
    """바꿀 말 목록 — 조사를 뗀 핵심어와 앞뒤 문맥. 교사 데이터(make_teacher.py)와 실행이 같은 함수를 쓴다"""
    items = []
    for s in list(spans)[:max_spans]:
        sp = josa.split_tail(s["text"], loc=s["type"] in ("LOC_ADMIN", "LOC_FACILITY", "REL_HOME", "REL_WORK"))
        items.append({**s, "core": sp.core, "before": text[:s["start"]], "after": text[s["end"]:],
                      "after_core": s["text"][len(sp.core):] + text[s["end"]:]})
    return items


def check(item: Mapping[str, Any], new_core: Any) -> tuple[str | None, str]:
    return _check(item, new_core)


def load_rewrite_adapter(model, path) -> str:
    """2단 모델(PeftModel)에 바꿔 쓰기 어댑터를 하나 더 얹는다. 이름을 돌려준다 — propose(adapter=이름)"""
    model.model.load_adapter(str(path), adapter_name="rewrite")
    model.model.set_adapter("default")
    return "rewrite"


def propose(model, text: str, spans: Sequence[Mapping[str, Any]], *, max_spans: int = 8,
            detector: Callable[[str], list[dict[str, Any]]] | None = None,
            adapter: str | None = None) -> dict[str, dict[str, Any]]:
    """model — kopl.c4_stage2.infer.Stage2Model (어댑터를 이 호출 동안만 끈다).

    → {span_id: {"suggestion": str | None, "core": 모델이 낸 말, "reason": 거른 이유, "residual": bool | None}}
    detector(text) 를 주면 바꾼 글에서 같은 자리 · 같은 유형 단서가 또 잡히는 후보를 거른다(잔존).
    """
    items = make_items(text, spans, max_spans=max_spans)
    if not items:
        return {}
    tok, peft_model, torch = model.tok, model.model, model._torch
    prompt = tok.apply_chat_template(build_messages(text, items), tokenize=False, add_generation_prompt=True,
                                     enable_thinking=False)
    ids = tok(prompt, return_tensors="pt").to(peft_model.device)
    gen = dict(max_new_tokens=40 + 25 * len(items), do_sample=False, temperature=None, top_p=None, top_k=None)
    if adapter:  # 학습한 바꿔 쓰기 어댑터 — 끝나면 2단 어댑터(default)로 되돌린다
        peft_model.set_adapter(adapter)
        try:
            with torch.no_grad():
                out = peft_model.generate(**ids, **gen)
        finally:
            peft_model.set_adapter("default")
    else:  # 기본 모델 (v1)
        with torch.no_grad(), peft_model.disable_adapter():
            out = peft_model.generate(**ids, **gen)
    raw = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception:  # noqa: BLE001
        data = {}
    result: dict[str, dict[str, Any]] = {}
    for i, it in enumerate(items, 1):
        new_core = data.get(str(i))
        sug, reason = _check(it, new_core)
        residual = None
        if sug and detector is not None:
            new_text = text[:it["start"]] + sug + text[it["end"]:]
            lo, hi = it["start"], it["start"] + len(sug)
            residual = any(d["type"] == it["type"] and d["start"] < hi and lo < d["end"] for d in detector(new_text))
            if residual:
                sug, reason = None, "바꿔도 단서가 다시 잡힘"
        result[it["span_id"]] = {"suggestion": sug, "core": new_core, "reason": reason, "residual": residual}
    return result


def apply(text: str, start: int, end: int, suggestion: str) -> str:
    return text[:start] + suggestion + text[end:]
