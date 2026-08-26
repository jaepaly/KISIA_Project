"""인물 JSON 검증기.

생성 전에 먼저 통과해야 하는 게이트. B·C·D·E가 인물 JSON을 제출할 때도
같은 스크립트를 돌린다.

    python validate.py data/corpus/v0/personas/*.json

ERROR가 하나라도 있으면 exit code 1. 생성 파이프라인은 ERROR 인물을 건너뛴다.
"""

from __future__ import annotations

import glob
import json
import re
import sys
import unicodedata
from pathlib import Path

# ── 계약 상수 ─────────────────────────────────────────────────────────
# 7속성 키 이름은 persona-design.md §4-1 · C의 특정성 축 · 계약 4종과 동일해야 한다.
ATTRS = ("age", "sex", "location", "occupation", "family", "commute", "income")
LEVELS = ("explicit", "implicit", "inferential")
# label-schema.md §4-2 / stage2-io.schema.json 과 동일해야 한다.
#   self    기본
#   other   명시적으로 타인에게 귀속
#   unknown 문장만으로 판단 불가
# 다만 clue_plan.subject 는 "설계자가 의도한 귀속"이라 구조적으로 unknown 이 나오지 않는다
# (설계자는 항상 소유자를 안다). 스팬 라벨 쪽에서 판독 결과로 나오는 값이다.
# 값 집합은 계약과 맞추되, clue_plan 에 unknown 이 오면 경고한다.
SUBJECTS = ("self", "other", "unknown")
SEXES = ("M", "F")

# RULES-DO-NOT: 방어 도구가 민감 속성 추론을 학습하면 그 자체가 무기가 된다.
FORBIDDEN_TERMS = (
    "학력", "학벌", "전공", "졸업", "학번", "수능", "편입",
    "정치", "지지율", "보수", "진보", "투표",
    "건강", "지병", "진단", "복용", "수술", "우울", "장애",
    "아이큐", "지능", "종교", "교회", "성당", "절에",
)

# 노이즈 정의 B안(개별 무해 기준).
#
# 인물 단위와 코퍼스 단위를 분리한다. 리얼리즘 카드가 채점표인데 카드마다
# 노이즈 목표가 다르다(예: S11 = 60%). 인물 전원을 70~80%에 맞추면 카드를
# 어기게 되고, 100명이 전부 같은 비율인 것 자체가 W3 분포 검증에서 부자연스럽다.
# 따라서 인물은 넓은 밴드로 경고만 하고, 70~80% 판정은 코퍼스 합산에서 한다.
PERSONA_NOISE_BAND = (0.55, 0.85)   # 인물 단위 — WARN
CORPUS_NOISE_BAND = (0.70, 0.80)    # 코퍼스 합산 — 완료 기준

POST_ID_RE = re.compile(r"^b\d{2}$")

# ── 카드 공유 인물 간 목소리 대조 (persona-design.md §2-⑤) ──────────────
#
# 카드 → 인물 → 글 구조에서 카드 1장으로 인물 N명을 만든다. 이때 인물끼리
# 목소리가 안 갈리면 "전부 똑같은 AI"가 되고, 모델이 내용이 아니라 문체를 외운다.
#
# 다만 카드를 공유한다는 건 상위 톤을 공유한다는 뜻이라 전부 달라야 하는 건 아니다.
# 카드가 정하는 축은 겹쳐도 정상이고, 인물이 정하는 축이 겹치면 문제다.
CARD_BOUND_KEYS = ("종결어미", "격식", "톤", "말투")   # 카드가 정한다 — 겹쳐도 정상
VOICE_SIM_THRESHOLD = 0.6                              # 이 이상이면 "겹침"
MIN_DISTINCT_AXES = 4                                  # 인물 축은 최소 이만큼 달라야


def _bigrams(text: str) -> set:
    t = re.sub(r"[\s·,./·~()\[\]'\"]+", "", str(text))
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def _similarity(a, b) -> float:
    """자유서술은 문자 바이그램 자카드, 목록은 원소 자카드."""
    if isinstance(a, list) and isinstance(b, list):
        sa, sb = set(map(str, a)), set(map(str, b))
    else:
        sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def cross_check(personas: list[tuple[str, dict]]) -> list[str]:
    """같은 카드를 참조하는 인물끼리 목소리가 갈리는지 본다."""
    by_card: dict[str, list[tuple[str, dict]]] = {}
    for pid, d in personas:
        for ref in d.get("card_ref", []) or []:
            by_card.setdefault(ref, []).append((pid, d))

    lines: list[str] = []
    for card, group in sorted(by_card.items()):
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pid_a, a = group[i]
                pid_b, b = group[j]
                va = a.get("voice") or {}
                vb = b.get("voice") or {}
                rows, distinct, bound = [], 0, 0
                for k in sorted(set(va) & set(vb)):
                    sim = _similarity(va[k], vb[k])
                    is_bound = any(t in k for t in CARD_BOUND_KEYS)
                    if is_bound:
                        bound += 1
                        mark = "(카드 축)"
                    elif sim < VOICE_SIM_THRESHOLD:
                        distinct += 1
                        mark = "다름"
                    else:
                        mark = "⚠ 겹침"
                    rows.append(f"      {k:12} {sim:.2f}  {mark}")
                ta = a.get("noise_topics") or (va.get("소재") or [])
                tb = b.get("noise_topics") or (vb.get("소재") or [])
                if ta and tb:
                    sim = _similarity(ta, tb)
                    if sim < VOICE_SIM_THRESHOLD:
                        distinct += 1
                    rows.append(f"      {'소재':12} {sim:.2f}  "
                                f"{'다름' if sim < VOICE_SIM_THRESHOLD else '⚠ 겹침'}")

                total = len(rows) - bound
                ok = distinct >= min(MIN_DISTINCT_AXES, total)
                lines.append(f"  카드 {card}: {pid_a} ↔ {pid_b}")
                lines += rows
                lines.append(
                    f"      → 인물 축 {total}개 중 {distinct}개 다름 "
                    f"{'OK' if ok else f'⚠ {MIN_DISTINCT_AXES}개 이상 달라야 한다'}"
                )
    return lines


class Issue:
    __slots__ = ("level", "path", "msg")

    def __init__(self, level: str, path: str, msg: str) -> None:
        self.level, self.path, self.msg = level, path, msg

    def __str__(self) -> str:
        return f"  [{self.level:5}] {self.path}: {self.msg}"


def _scan_forbidden(text: str) -> list[str]:
    return [t for t in FORBIDDEN_TERMS if t in text]


def validate(persona: dict) -> list[Issue]:
    out: list[Issue] = []
    err = lambda p, m: out.append(Issue("ERROR", p, m))
    warn = lambda p, m: out.append(Issue("WARN", p, m))

    # ── 식별자 ────────────────────────────────────────────────────────
    pid = persona.get("id") or persona.get("persona_id")
    if not pid:
        err("id", "id 또는 persona_id가 없다")
    elif "persona_id" in persona and "id" in persona:
        warn("id", "id와 persona_id가 둘 다 있다. 하나로 통일할 것")

    if persona.get("synthetic") is not True:
        err("synthetic", 'synthetic: true 가 아니다. 실데이터 유입 의심 — 커밋 금지')

    # ── ground_truth 7속성 ────────────────────────────────────────────
    gt = persona.get("ground_truth")
    if not isinstance(gt, dict):
        err("ground_truth", "없거나 객체가 아니다")
        gt = {}
    else:
        for a in ATTRS:
            if a not in gt:
                err(f"ground_truth.{a}", "7속성 중 누락")
        for k in gt:
            if k not in ATTRS:
                err(f"ground_truth.{k}", f"7속성 밖의 키. 허용: {', '.join(ATTRS)}")
        if gt.get("sex") not in SEXES and "sex" in gt:
            err("ground_truth.sex", f"{gt.get('sex')!r} — M 또는 F만 허용")
        if not isinstance(gt.get("age"), int) and "age" in gt:
            warn("ground_truth.age", "정수가 아니다. C의 연령대 집계가 깨질 수 있다")

    # ── post_plan 산술 ────────────────────────────────────────────────
    plan = persona.get("post_plan", {})
    total = plan.get("total", 0)
    parts = {k: plan.get(k, 0) for k in ("noise", "ambient", "clue", "trap")}
    if not total:
        err("post_plan.total", "없다")
    elif sum(parts.values()) != total:
        err("post_plan", f"noise+ambient+clue+trap={sum(parts.values())} ≠ total={total}")

    clue_plan = persona.get("clue_plan", []) or []
    if len(clue_plan) != parts["clue"] + parts["trap"]:
        err(
            "clue_plan",
            f"항목 {len(clue_plan)}개 ≠ post_plan의 clue({parts['clue']})+trap({parts['trap']})",
        )

    # ── clue_plan 각 항목 ─────────────────────────────────────────────
    seen: dict[str, str] = {}
    for i, c in enumerate(clue_plan):
        p = f"clue_plan[{i}]"
        post = c.get("post", "")
        if not POST_ID_RE.match(post):
            err(p, f"post={post!r} — b01 형식이어야 한다")
        elif post in seen:
            err(p, f"post={post} 가 {seen[post]} 와 중복")
        else:
            seen[post] = p
        if total and POST_ID_RE.match(post) and int(post[1:]) > total:
            err(p, f"post={post} 가 total({total})을 넘는다")

        if c.get("attr") not in ATTRS:
            err(p, f"attr={c.get('attr')!r} — 7속성 밖")
        if c.get("level") not in LEVELS:
            err(p, f"level={c.get('level')!r} — {'/'.join(LEVELS)} 중 하나")
        if "subject" in c and c["subject"] not in SUBJECTS:
            err(p, f"subject={c['subject']!r} — {'/'.join(SUBJECTS)} 중 하나")
        if c.get("subject") == "unknown":
            warn(
                p,
                "clue_plan.subject 는 설계 의도라 unknown 이 나올 자리가 아니다. "
                "문장만으로 판단 불가한 표본을 노렸다면 subject 는 self/other 로 두고 "
                "ambiguous: true 를 쓸 것",
            )
        if "ambiguous" in c and not isinstance(c["ambiguous"], bool):
            err(p, f"ambiguous={c['ambiguous']!r} — true/false 여야 한다")

        hit = _scan_forbidden(str(c.get("clue", "")) + str(c.get("note", "")))
        if hit:
            err(p, f"금지 속성 단서: {', '.join(hit)} — RULES-DO-NOT 위반")

    # ambiguous 표본 — 기대 라벨이 unknown 인 글. IAA subject 일치도 측정용
    amb = [c for c in clue_plan if c.get("ambiguous")]
    if amb and total:
        out.append(Issue("INFO", "clue_plan",
                         f"ambiguous 표본 {len(amb)}건 ({len(amb) / total:.0%}) "
                         f"— 기대 라벨 unknown"))

    # ── ambient / noise 배분 ──────────────────────────────────────────
    ambient = (persona.get("ambient_plan") or {}).get("posts", []) or []
    for post in ambient:
        if post in seen:
            err("ambient_plan.posts", f"{post} 가 clue_plan에도 있다")
    if len(ambient) != parts["ambient"]:
        err("ambient_plan.posts", f"{len(ambient)}개 ≠ post_plan.ambient({parts['ambient']})")

    # 노이즈 비율 B안: 단서 보유 편수(clue+trap) 기준
    if total:
        noise = 1 - len(clue_plan) / total
        lo, hi = PERSONA_NOISE_BAND
        if not lo <= noise <= hi:
            warn(
                "post_plan",
                f"노이즈 {noise:.0%} — 인물 밴드 {lo:.0%}~{hi:.0%} 밖. "
                f"참조 카드의 노이즈 목표와 맞는지 확인",
            )

    # ── 소재 축 (persona-design.md §2-⑤) ──────────────────────────────
    topics = persona.get("noise_topics") or (persona.get("voice") or {}).get("소재")
    if not topics:
        warn(
            "noise_topics",
            "잡담 소재가 지정되지 않았다. §2-⑤ 는 '소재'를 목소리 차별화 축으로 둔다 — "
            "없으면 인물 간 잡담이 같은 소재로 수렴한다",
        )
    elif isinstance(topics, list) and len(topics) < 5:
        warn("noise_topics", f"{len(topics)}개 — 잡담 글 수만큼 있어야 반복되지 않는다")

    # ── voice ─────────────────────────────────────────────────────────
    voice = persona.get("voice") or {}
    if not voice:
        err("voice", "없다. 문체가 인물마다 갈리지 않으면 모델이 내용이 아니라 문체를 외운다")
    elif len(voice) < 4:
        warn("voice", f"항목 {len(voice)}개 — 종결어미·문장길이·오타율·말버릇은 최소한 넣을 것")

    # ── 전역 금지어 (clue 밖은 경고) ──────────────────────────────────
    # design_note.prohibited 는 금지어를 나열하는 게 목적이므로 스캔에서 뺀다.
    scan_target = {k: v for k, v in persona.items() if k != "design_note"}
    dn = {k: v for k, v in (persona.get("design_note") or {}).items() if k != "prohibited"}
    if dn:
        scan_target["design_note"] = dn
    blob = json.dumps(scan_target, ensure_ascii=False)
    hit = _scan_forbidden(blob)
    if hit:
        warn("*", f"금지 속성 어휘 발견: {', '.join(hit)} — 단서가 아닌지 확인")

    # ── 정규화 ────────────────────────────────────────────────────────
    if blob != unicodedata.normalize("NFC", blob):
        err("*", "NFC 정규화되지 않았다. 문자 offset이 팀원 간에 어긋난다")

    return out


def validate_file(path: Path) -> tuple[bool, list[Issue]]:
    try:
        persona = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        return False, [Issue("ERROR", str(path), f"JSON 파싱 실패: {e}")]
    issues = validate(persona)
    return not any(i.level == "ERROR" for i in issues), issues


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    # PowerShell 은 와일드카드를 펼치지 않고 그대로 넘긴다. 여기서 직접 처리한다.
    files: list[Path] = []
    for a in argv:
        hits = sorted(glob.glob(a))
        if hits:
            files += [Path(h) for h in hits]
        else:
            files.append(Path(a))
    if not files:
        print("검증할 파일이 없다")
        return 2
    bad = 0
    tot_posts = tot_clue = tot_amb = 0
    loaded: list[tuple[str, dict]] = []
    for f in files:
        ok, issues = validate_file(f)
        mark = "OK  " if ok else "FAIL"
        print(f"{mark} {f.name}" + (f"  ({len(issues)} issue)" if issues else ""))
        for i in issues:
            print(i)
        if not ok:
            bad += 1
            continue
        d = json.loads(f.read_text(encoding="utf-8-sig"))
        tot_posts += d.get("post_plan", {}).get("total", 0)
        tot_clue += len(d.get("clue_plan", []))
        tot_amb += sum(1 for c in d.get("clue_plan", []) if c.get("ambiguous"))
        loaded.append((d.get("id") or d.get("persona_id") or f.stem, d))

    print(f"\n{len(files) - bad}/{len(files)} 통과")

    # 완료 기준 판정은 여기다 — 인물 하나가 아니라 코퍼스 합산
    if tot_posts:
        noise = 1 - tot_clue / tot_posts
        lo, hi = CORPUS_NOISE_BAND
        ok = lo <= noise <= hi
        print(
            f"코퍼스 합산 노이즈 {noise:.0%} "
            f"({tot_posts - tot_clue}/{tot_posts}편) "
            f"— {'OK' if ok else f'⚠ 완료 기준 {lo:.0%}~{hi:.0%} 밖'}"
        )
        if not ok and len(files) > 1:
            bad += 1

    cross = cross_check(loaded)
    if cross:
        print("\n[카드 공유 인물 간 목소리 대조 — §2-⑤]")
        print("\n".join(cross))

    if tot_clue:
        print(
            f"ambiguous 표본 {tot_amb}/{tot_clue}건 ({tot_amb / tot_clue:.0%}) "
            f"— subject=unknown 기대. W3 IAA 측정 표본"
        )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
