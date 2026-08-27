"""인물 JSON → 게시글 생성 파이프라인.

    # 오늘: 키 없이 배선 확인
    python generate.py --persona S01.json --out ./posts --provider echo

    # 팀이 API를 정한 뒤
    python generate.py --persona data/corpus/v0/personas/*.json \\
        --out data/corpus/v0/posts --provider anthropic

핵심 설계 두 가지:
1) 노이즈 비율은 프롬프트가 아니라 코드가 통제한다. 모델에게 "20편 중 5편에만
   단서를 넣어라"라고 시키면 비율이 안 지켜진다. 글 1편마다 kind를 먼저 정하고
   그에 맞는 지시를 붙인다.
2) 글 1편 = 호출 1번. 한 번에 20편을 뽑으면 문체가 수렴하고 문장 길이가 고르게
   나와서 리얼리즘 검수 2번 항목에서 걸린다.
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import prompts
from llm import LLMClient, LLMError, check_generation_model, list_models, load_dotenv
from validate import validate_file

KST = timezone(timedelta(hours=9))
CORPUS_SCHEMA_VERSION = "0.1"  # 인물 JSON의 schema_version과 다른 값이다


# ── 글 분류 ──────────────────────────────────────────────────────────
def classify_posts(persona: dict) -> list[dict]:
    """b01..bNN 각각에 kind를 배정한다. 이게 노이즈 비율의 유일한 통제 지점."""
    total = persona["post_plan"]["total"]
    clues = {c["post"]: c for c in persona.get("clue_plan", [])}
    ambient = set((persona.get("ambient_plan") or {}).get("posts", []))
    design = (persona.get("ambient_plan") or {}).get("design", "")

    out = []
    for n in range(1, total + 1):
        pid = f"b{n:02d}"
        if pid in clues:
            out.append({"post": pid, "kind": "clue", "clue": clues[pid]})
        elif pid in ambient:
            out.append({"post": pid, "kind": "ambient", "design": design})
        else:
            out.append({"post": pid, "kind": "noise"})
    return out


def stratified_sample(plan: list[dict], n: int, rng: random.Random) -> list[dict]:
    """전체 계획에서 n편만 뽑되 kind 구성비를 유지한다.

    앞에서부터 n편을 자르면 단서/지역/잡담 구성이 우연에 맡겨진다. 시범의 목적이
    "세 갈래 프롬프트가 다 도는가"라서 각 kind가 최소 1편씩은 들어가야 한다.
    단서는 level이 겹치지 않게 먼저 고른다 — explicit만 3편 뽑으면 의미가 없다.
    """
    if n >= len(plan):
        return plan
    buckets: dict[str, list[dict]] = {"clue": [], "ambient": [], "noise": []}
    for item in plan:
        buckets[item["kind"]].append(item)

    quota = {}
    for k, items in buckets.items():
        quota[k] = min(len(items), max(1 if items else 0, round(n * len(items) / len(plan))))
    # 반올림 오차 보정. n이 kind 수보다 작으면 0까지 내려간다 (스모크 테스트 1편 등).
    # 줄일 때는 잡담 → 지역 → 단서 순. 단서 글이 프롬프트가 가장 복잡해서
    # 1편만 뽑을 때 그게 나와야 실패를 빨리 본다.
    REDUCE_FIRST = {"noise": 2, "ambient": 1, "clue": 0}
    while sum(quota.values()) > n:
        k = max(quota, key=lambda x: (quota[x], REDUCE_FIRST[x]))
        if quota[k] == 0:
            break
        quota[k] -= 1
    while sum(quota.values()) < n:
        k = max(quota, key=lambda x: len(buckets[x]) - quota[x])
        if quota[k] >= len(buckets[k]):
            break
        quota[k] += 1

    picked: list[dict] = []
    for k, items in buckets.items():
        if k == "clue":
            # level 다양성 우선
            by_level: dict[str, list[dict]] = {}
            for it in items:
                by_level.setdefault(it["clue"].get("level", "?"), []).append(it)
            order, levels = [], sorted(by_level)
            while len(order) < len(items):
                for lv in levels:
                    if by_level[lv]:
                        order.append(by_level[lv].pop(0))
            picked += order[: quota[k]]
        else:
            step = max(1, len(items) // max(1, quota[k]))
            picked += items[::step][: quota[k]]
    return sorted(picked, key=lambda x: x["post"])


# ── 게시 시각 ────────────────────────────────────────────────────────
def sample_time(persona: dict, rng: random.Random, idx: int) -> str:
    """활동 시간대 자체가 재식별 신호다. 인물마다 다르게 찍어야 의미가 있다.

    account.active_windows 가 있으면 그걸 쓰고, 없으면 일반 패턴으로 떨어진다.
    (typical_active_hours 는 자유서술이라 파싱하지 않는다 — 구조화 필드 권장)
    """
    windows = (persona.get("account") or {}).get("active_windows")
    base = datetime(2026, 3, 2, tzinfo=KST) + timedelta(days=idx * rng.randint(2, 6))
    if windows:
        w = rng.choice(windows)
        hour = rng.randint(w.get("start_hour", 20), w.get("end_hour", 23))
    else:
        hour = rng.choice([21, 22, 22, 23, 23, 10, 11])
    return base.replace(
        hour=hour % 24, minute=rng.randint(0, 59), second=rng.randint(0, 59)
    ).isoformat()


# ── 응답 파싱 ────────────────────────────────────────────────────────
def parse(raw: str) -> tuple[str, str]:
    text = unicodedata.normalize("NFC", raw).strip()
    title, body = "", text
    for line in text.splitlines():
        if line.strip().startswith("제목:"):
            title = line.split(":", 1)[1].strip()
            body = text.split(line, 1)[1].strip()
            break
    return title, body


# ── 인물 1명 생성 ────────────────────────────────────────────────────
def generate_persona(
    persona: dict, client: LLMClient, out_dir: Path, cards_dir: Path | None,
    seed: int, sample: int = 0, sleep: float = 0.0, inject_cards: bool = False
) -> dict:
    pid = persona.get("id") or persona["persona_id"]
    rng = random.Random(f"{pid}:{seed}")
    out_path = out_dir / f"{pid}.jsonl"

    # resume: 이미 뽑은 post_id는 건너뛴다. 150편째에 끊겨도 처음부터 안 돈다.
    done: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                # 저장된 post_id는 "S01_b03" 형태다. 루프는 "b03"로 비교하므로 접두어를 뗀다.
                done.add(json.loads(line)["post_id"].rsplit("_", 1)[-1])
        if done:
            print(f"  resume — {len(done)}편 건너뜀")

    card_text = ""
    if cards_dir and inject_cards:
        for ref in persona.get("card_ref", []):
            for f in sorted(cards_dir.glob(f"{ref}_*.md")) + sorted(cards_dir.glob(f"{ref}.md")):
                card_text += f.read_text(encoding="utf-8-sig") + "\n"
                break
    # 주입하지 않아도 card_ref 가 실제 카드를 가리키는지는 확인한다
    if cards_dir and persona.get("card_ref"):
        missing = [
            r for r in persona["card_ref"]
            if not (list(cards_dir.glob(f"{r}_*.md")) or list(cards_dir.glob(f"{r}.md")))
        ]
        if missing:
            print(f"  ⚠ card_ref {missing} 에 해당하는 카드 파일이 없다")
    if inject_cards:
        print("  ⚠ 카드 원문 주입 모드 — persona-design.md §6 이탈. 같은 카드 참조 인물끼리 문체가 수렴한다")

    system = prompts.build_system(persona, card_text)
    # persona-design.md §2-⑤ 소재 축. 인물이 지정하지 않으면 전역 폴백을 쓰되 경고한다.
    topics = persona.get("noise_topics") or (persona.get("voice", {}) or {}).get("소재")
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split("/") if t.strip()]
    if not topics:
        topics = prompts.FALLBACK_NOISE_TOPICS
        print("  ⚠ noise_topics 없음 — 전역 폴백 사용. 인물 간 잡담 소재가 겹친다 (§2-⑤ 소재 축)")
    topic_offset = rng.randrange(len(topics))
    noise_seen = 0
    full_plan = classify_posts(persona)
    plan = stratified_sample(full_plan, sample, rng) if sample else full_plan
    if sample and len(plan) < len(full_plan):
        mix = {k: sum(1 for i in plan if i["kind"] == k) for k in ("clue", "ambient", "noise")}
        print(f"  시범 {len(plan)}/{len(full_plan)}편 — 단서 {mix['clue']} · 지역 {mix['ambient']} · 잡담 {mix['noise']}")
    # 설계상 노이즈 비율은 항상 전체 계획 기준으로 감사한다 (시범 표본으로 판정하지 않는다)
    counts = {k: sum(1 for i in full_plan if i["kind"] == k) for k in ("clue", "ambient", "noise")}
    written = 0

    with out_path.open("a", encoding="utf-8") as fh:
        for idx, item in enumerate(plan):
            if item["post"] in done:
                continue
            topic = ""
            if item["kind"] == "noise":
                topic = topics[(noise_seen + topic_offset) % len(topics)]
                noise_seen += 1
            user = prompts.build_user(
                item["kind"], item.get("clue"), item.get("design", ""), topic
            )
            if sleep and written:
                time.sleep(sleep)
            try:
                raw = client.complete(system, user)
            except LLMError as e:
                print(f"  ✗ {item['post']} 실패: {e}")
                continue
            title, body = parse(raw)
            if getattr(client, "last_truncated", False):
                print(f"  ✗ {item['post']} 잘림 — 저장하지 않는다. --max-tokens 를 올려라")
                continue
            rec = {
                "post_id": f"{pid}_{item['post']}",
                "persona_id": pid,
                "title": title,
                "body": body,
                "n_chars": len(body),  # 문자 offset 기준 라벨의 sanity check용
                "created_at": sample_time(persona, rng, idx),
                "nickname": (persona.get("account") or {}).get("nickname", ""),
                "kind": item["kind"],
                # label-schema §8-3 — 단서를 의도적으로 넣지 않은 글인가
                "negative_control": item["kind"] == "noise",
                "clue": item.get("clue"),
                # 재현 메타 — 없으면 10주 뒤에 이 글이 뭐였는지 복원 못 한다
                # 재현 메타 (이슈 4-② / RULES-DO-NOT #9)
                "gen_model": client.version,
                "prompt_version": prompts.PROMPT_VERSION,
                "generated_at": datetime.now(KST).isoformat(),
                "persona_schema_version": persona.get("schema_version", "?"),
                "card_ref": persona.get("card_ref", []),
                "corpus_schema_version": CORPUS_SCHEMA_VERSION,
                "synthetic": True,
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()  # 중간에 끊겨도 여기까지는 남는다
            written += 1
            print(f"  {item['post']} [{item['kind']:7}] {len(body):4}자  {title[:20]}")

    total = len(full_plan)
    noise_ratio = (counts["ambient"] + counts["noise"]) / total
    return {
        "persona_id": pid,
        "total": total,
        "written": written,
        "counts": counts,
        "noise_ratio": round(noise_ratio, 3),
        "planned": len(plan),
        "persona_schema_version": persona.get("schema_version", "?"),
        "card_ref": persona.get("card_ref", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", nargs="*", default=[])
    ap.add_argument("--list-models", action="store_true",
                    help="내 키로 쓸 수 있는 모델 ID를 조회하고 종료")
    ap.add_argument("--out", default="data/corpus/v0/posts")
    ap.add_argument("--cards", default=None,
                    help="data/realism/cards — card_ref 존재 확인용")
    ap.add_argument("--inject-cards", action="store_true",
                    help="카드 원문을 프롬프트에 주입 (실험용). persona-design.md §6 이탈")
    ap.add_argument("--provider", default="echo")
    ap.add_argument("--model", default=None)
    ap.add_argument("--cli-cmd", default="", help="--provider cli 일 때 (예: 'codex exec -')")
    ap.add_argument("--sample", type=int, default=0,
                    help="인물당 n편만 시범 생성 (kind 구성비 유지). 수요일 시범은 5")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="호출 간 대기(초). 무료 티어 RPM 제한 회피용. Gemini 무료면 5 권장")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=4096,
                    help="출력 토큰 상한. 사고 토큰을 쓰는 모델은 넉넉히 줘야 본문이 안 잘린다")
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--skip-invalid", action="store_true", help="ERROR 인물을 건너뛰고 계속")
    args = ap.parse_args()

    if args.list_models:
        try:
            ms = list_models(args.provider)
        except LLMError as e:
            print(f"✗ {e}")
            return 2
        print(f"[{args.provider}] 사용 가능 모델 {len(ms)}개")
        for m in ms:
            blocked = any(f in m.lower() for f in ("claude", "qwen"))
            print(f"  {'✗ 생성 금지' if blocked else '  '} {m}")
        return 0

    if not args.persona:
        ap.error("--persona 가 필요하다")

    loaded = load_dotenv()
    if loaded:
        print(f"(.env 에서 {loaded}개 변수 로드)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cards_dir = Path(args.cards) if args.cards else None
    if args.provider == "cli" and not args.model:
        print("✗ --provider cli 는 --model 이 필요하다.\n"
              "    --cli-cmd 의 -m 값과 같은 것을 넣어라. 앞은 기록용(gen_model),\n"
              "    뒤가 실제 실행이다. 없으면 어느 모델로 뽑은 코퍼스인지 복원할 수 없다.\n"
              "    예: --model gpt-5.6-sol --cli-cmd \"codex exec --sandbox read-only -m gpt-5.6-sol -\"")
        return 2

    try:
        # 이슈 1항: 생성 경로에 Claude·Qwen 계열이 들어오면 여기서 멈춘다
        check_generation_model(args.provider, args.model or "", args.cli_cmd)
    except LLMError as e:
        print(f"✗ {e}")
        return 2
    client = LLMClient(args.provider, args.model, args.temperature,
                       max_tokens=args.max_tokens, cli_cmd=args.cli_cmd)
    check_generation_model(args.provider, client.model, args.cli_cmd)  # 기본 모델도 검사

    if args.provider == "echo":
        print("⚠ echo 모드 — 더미 텍스트다. 코퍼스로 커밋하지 마라.\n")

    # PowerShell 은 와일드카드를 펼치지 않는다
    persona_paths: list[str] = []
    for a in args.persona:
        hits = sorted(glob.glob(a))
        persona_paths += hits if hits else [a]
    if not persona_paths:
        print("인물 JSON 을 찾지 못했다")
        return 2
    print(f"인물 {len(persona_paths)}개\n")

    summaries = []
    for p in persona_paths:
        path = Path(p)
        print(f"■ {path.name}")
        ok, issues = validate_file(path)
        for i in issues:
            print(i)
        if not ok:
            print("  검증 실패 — 생성 건너뜀\n")
            if not args.skip_invalid:
                return 1
            continue
        persona = json.loads(path.read_text(encoding="utf-8-sig"))
        summaries.append(
            generate_persona(
                persona, client, out_dir, cards_dir, args.seed, args.sample, args.sleep,
                args.inject_cards
            )
        )
        print()

    print("=" * 60)
    written = design_total = 0
    for s in summaries:
        print(
            f"{s['persona_id']}  신규 {s['written']:3}편  "
            f"[설계 {s['total']}편: 단서 {s['counts']['clue']} · 지역 {s['counts']['ambient']} "
            f"· 잡담 {s['counts']['noise']} → 노이즈 {s['noise_ratio']:.0%}]  "
            f"카드 {','.join(s['card_ref']) or '-'}"
        )
        written += s["written"]
        design_total += s["total"]

    # 코퍼스 전체 노이즈 비율 — 개별 인물이 아니라 여기가 70~80% 판정 지점
    if design_total:
        agg = sum(
            (x["counts"]["ambient"] + x["counts"]["noise"]) for x in summaries
        ) / design_total
        flag = "OK" if 0.70 <= agg <= 0.80 else "⚠ 70~80% 범위밖"
        print(f"\n코퍼스 합산 노이즈 {agg:.0%} {flag}  (인물 {len(summaries)}명 · 설계 {design_total}편)")

    print(f"\n[한도 소모 — 이슈 5항 보고용]  {client.version}")
    print(client.burn_report(written))

    (out_dir / "_summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
