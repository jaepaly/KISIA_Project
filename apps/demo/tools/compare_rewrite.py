"""리라이트 후보 비교 — 규칙 경로 vs Claude(문장만) vs Claude(문맥 포함).

    python apps/demo/tools/compare_rewrite.py            # .env 의 ANTHROPIC_API_KEY 를 읽는다. 없으면 규칙 경로만

떠 있는 서버는 건드리지 않는다 — 엔진을 직접 부른다. 문장·구간만 API 로 나가고 글 전체·닉네임은 안 나간다.
「문맥 포함」 안은 앞뒤 문장과 이미 고른 사다리 단(진영읍 → 김해시 …)을 같이 주는 프롬프트 초안이다 — 채택되면 engine/external.py 로 옮긴다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "apps" / "demo"))


def load_env() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:                                   # 같은 이름이 여러 줄이면 값이 있는 마지막 줄이 이긴다 (.env.example 의 빈 줄 때문)
            os.environ[k.strip()] = v


CASES = [
    ("난 김해시 진영읍에 산다. 쉰셋이 되니 무릎이 아프다.", "김해시 진영읍"),
    ("집 앞 정류장에서 7호선 타고 출근한다.", "집 앞"),
    ("집 앞 정류장에서 7호선 타고 출근한다.", "정류장"),
    ("예순여덟인디 아직 이만하면 다닐 만 하다.", "예순여덟"),
    ("아 맞다, 면사무소 앞에서 기다렸는디 버스가 한 시간에 한 대라 그냥 걸어왔다.", "면사무소 앞에서 기다렸는디 버스가 한 시간에 한 대라"),
    ("근데 나 나이 스물셋임.", "스물셋"),
    ("용마산역 근처에 산다. 태릉입구에서 7호선 타고 출근한다.", "용마산역"),
]


def rule_candidates(sentence: str, span_text: str) -> list[dict]:
    os.environ["DEMO_EXTERNAL_REWRITE"] = ""
    from engine.detect import detect_post
    from engine.pipeline import analyze
    from engine.recommend import candidates_for, ladder_candidates
    export = {"schema_version": "1.0", "user_ref": "u_t", "nickname": "t", "profile_bio": None,
              "posts": [{"post_id": "p1", "title": None, "body": sentence, "photos": [], "activity_meta": {},
                         "created_at": "2026-01-01T00:00:00+09:00", "visibility": "public"}]}
    view = analyze(export)
    p = view["posts"][0]
    sp = next((s for s in p["spans"] if s["text"] == span_text), None)
    if sp is None:
        return [{"text": "(탐지 안 됨)", "note": ""}]
    widen = ladder_candidates(view, "p1", sp, p["notes"].get(sp["span_id"], {}))
    cands, _ = candidates_for(sentence, sp)
    return ([{"text": w["text"], "note": w["note"] + f" → {w['k']:,}명"} for w in widen] + cands)[:4]


def claude(sentence: str, span_text: str, context: dict | None) -> list[dict]:
    from engine.external import _client
    client = _client()
    system = ("너는 한국어 글의 프라이버시 리라이터다. 주어진 문장에서 표시된 구간만 바꾼다. "
              "말투·어미·방언은 그대로 두고, 신상(지명·행정단위·배차 간격·나이·소득 주기)이 새는 정보만 지운다. "
              "후보 3개를 낸다: ① 정보만 지운 최소 수정, ② 표현을 조금 더 바꾼 안, ③ 이유 자체를 바꾼 안. "
              'JSON 배열만 출력한다: [{"text": "...", "note": "..."}]')
    user = f"문장: {sentence}\n바꿀 구간: {span_text}\n말투 힌트: 평서형 · 구어체 어미 · 방언 유지"
    if context:
        system += (" 문맥 규칙: 같은 문장 안에서 이미 바뀐 구간이 있으면 그 표현과 겹치거나 반복되지 않게 한다. "
                   "앞뒤 문장과 자연스럽게 이어져야 한다. 바꾼 뒤 문장 전체를 소리 내어 읽었을 때 어색하면 안 된다.")
        user += (f"\n앞 문장: {context.get('prev') or '(없음)'}\n뒤 문장: {context.get('next') or '(없음)'}"
                 f"\n이미 바뀐 구간: {context.get('already') or '(없음)'}"
                 f"\n넓히기 사다리(이 구간을 지우지 않고 넓힐 때 쓸 수 있는 상위 표현): {context.get('ladder') or '(없음)'}")
    msg = client.messages.create(model=os.getenv("DEMO_EXTERNAL_MODEL", "claude-haiku-4-5-20251001"), max_tokens=512,
                                 system=system, messages=[{"role": "user", "content": user}])
    content = msg.content[0].text.strip()
    if content.startswith("```"):
        content = content.strip("`").split("\n", 1)[1] if "\n" in content else content.strip("`")
    return [{"text": str(a["text"]).strip(), "note": str(a.get("note", "")).strip()} for a in json.loads(content)][:3]


def main() -> None:
    load_env()
    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    print("Claude 경로:", "켬" if has_key else "꺼짐 (.env 에 ANTHROPIC_API_KEY 도 ANTHROPIC_AUTH_TOKEN 도 없다 — 규칙 경로만)")
    contexts = {
        "정류장": {"prev": None, "next": None, "already": "「집 앞」 → 「근처」", "ladder": None},
        "김해시 진영읍": {"prev": None, "next": "쉰셋이 되니 무릎이 아프다.", "already": None, "ladder": "김해시 → 경남"},
        "용마산역": {"prev": None, "next": "태릉입구에서 7호선 타고 출근한다.", "already": None, "ladder": "중랑구 → 서울"},
        "예순여덟": {"prev": None, "next": None, "already": None, "ladder": "60대"},
        "스물셋": {"prev": None, "next": None, "already": None, "ladder": "20대"},
    }
    for sentence, span in CASES:
        print("\n" + "=" * 100)
        print(f"문장: {sentence}\n구간: 「{span}」")
        rules = rule_candidates(sentence, span)
        print("  [규칙]     " + " | ".join(f"「{c['text']}」 {c['note']}" for c in rules))
        if has_key:
            try:
                a = claude(sentence, span, None)
                print("  [Claude]   " + " | ".join(f"「{c['text']}」 {c['note']}" for c in a))
                b = claude(sentence, span, contexts.get(span, {"prev": None, "next": None, "already": None, "ladder": None}))
                print("  [Claude+문맥] " + " | ".join(f"「{c['text']}」 {c['note']}" for c in b))
            except Exception as e:  # noqa: BLE001
                print("  [Claude]   실패:", e.__class__.__name__, str(e)[:120])


if __name__ == "__main__":
    main()
