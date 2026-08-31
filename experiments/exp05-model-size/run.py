"""2단 모델 크기 측정 — qwen3:1.7b vs qwen3:4b.

    python experiments/exp05-model-size/run.py --model qwen3:4b
    python experiments/exp05-model-size/run.py --model qwen3:1.7b --think

판정 축 (README W3 D절 · D-stage2.md §4)
  ① 계약 과제 — findings 7속성 verdict 적중          ← 주 지표
  ② 값 추론 프로브 — scoring_keywords 부분일치        ← 부 지표
  ③ 근거 — evidence 가 실제 span_id 인가 · 함정을 근거로 썼나
  ④ 형식 준수율
  ⑤ 토큰 · 지연 (동률일 때만)

⚠️ **format 에 Stage2Output 전체를 넣지 않는다.** 그 스키마는 recommendation·provenance 도
   required 라, 크기 비교에 관계없는 부가 작업이 섞여 결과를 흐린다. findings 부분만
   같은 모양으로 떼어 쓴다. 두 모델에 같은 스키마가 가므로 비교는 성립한다.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
VERDICTS = ("specified", "narrowed", "weak_signal", "abstain")

FINDING = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["verdict", "evidence", "confidence"],
}
FORMAT = {
    "type": "object",
    "properties": {a: FINDING for a in ATTRS},
    "required": list(ATTRS),
}

SYSTEM = """너는 공개 게시글에서 글쓴이의 신상이 얼마나 특정되는지 판정하는 도구다.
아래 스팬 목록만 보고 7속성 각각을 판정한다.

verdict
  specified     그 속성이 사실상 확정된다
  narrowed      범위가 좁혀지지만 확정은 아니다
  weak_signal   신호는 있으나 약하다
  abstain       근거가 없다. 추측하지 마라

규칙
- evidence 에는 근거로 쓴 스팬의 span_id 만 배열로 넣는다. 문장을 넣지 마라.
- subject 가 "other" 인 스팬은 남의 정보다. 글쓴이 본인 속성의 근거로 쓰지 마라.
- 근거가 없으면 abstain 이고 evidence 는 빈 배열이다. 기권은 정상 동작이다.
- 실제 나이·지명 값을 쓰지 마라. 얼마나 특정되는가만 판정한다."""

PROBE_SYSTEM = """아래 스팬만 보고 글쓴이의 7속성을 추론해 값을 써라.
모르면 빈 문자열로 둔다. 추측이어도 좋다. JSON 만 출력한다."""
PROBE_FORMAT = {
    "type": "object",
    "properties": {a: {"type": "string"} for a in ATTRS},
    "required": list(ATTRS),
}


def call(model: str, system: str, user: str, fmt: dict, think: bool,
         num_predict: int, host: str) -> tuple[dict | None, dict]:
    body = {
        "model": model, "system": system, "prompt": user, "stream": False,
        "think": think, "format": fmt,
        "options": {"temperature": 0, "seed": 20260901, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        f"{host}/api/generate", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=900).read().decode("utf-8"))
    meta = {
        "sec": round(time.time() - t0, 2),
        "prompt_tokens": d.get("prompt_eval_count", 0),
        "eval_tokens": d.get("eval_count", 0),
        "done_reason": d.get("done_reason", ""),
    }
    try:
        return json.loads(d.get("response") or ""), meta
    except Exception:
        meta["raw"] = (d.get("response") or "")[:200]
        return None, meta


def render(spans: list[dict]) -> str:
    lines = ["스팬 목록:"]
    for s in spans:
        lines.append(
            f'- span_id={s["span_id"]} type={s["type"]} level={s["level"]}'
            f' subject={s["subject"]} text_id={s["text_id"]}\n  "{s["text"]}"')
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--think", action="store_true", help="사고 허용 (기본은 think:false)")
    ap.add_argument("--num-predict", type=int, default=2048)
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--probe", action="store_true", help="② 값 추론 프로브도 돌린다")
    a = ap.parse_args()

    items = json.loads((HERE / "input.json").read_text(encoding="utf-8"))
    if a.limit:
        items = items[: a.limit]

    tag = f"{a.model.replace(':', '-')}{'-think' if a.think else ''}"
    out = []
    print(f"■ {a.model} · think={a.think} · n={len(items)}")
    for i, it in enumerate(items, 1):
        user = render(it["spans"])
        res, meta = call(a.model, SYSTEM, user, FORMAT, a.think, a.num_predict, a.host)
        rec = {"persona_id": it["persona_id"], "findings": res, "meta": meta}
        if a.probe:
            p, pm = call(a.model, PROBE_SYSTEM, user, PROBE_FORMAT, a.think,
                         a.num_predict, a.host)
            rec["probe"] = p
            rec["probe_meta"] = pm
        out.append(rec)
        ok = "OK " if res else "형식✗"
        print(f"  {i:3}/{len(items)} {it['persona_id']:5} {ok} {meta['sec']:6.1f}s "
              f"{meta['eval_tokens']:5} tok")

    dst = HERE / "results" / f"raw_{tag}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    tot = sum(x["meta"]["sec"] for x in out)
    print(f"\n형식 통과 {sum(1 for x in out if x['findings'])}/{len(out)} · 합계 {tot:.0f}초")
    print(dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
