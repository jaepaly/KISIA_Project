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
SUBJECTS = ("self", "other")
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
            err(p, f"subject={c['subject']!r} — self 또는 other")

        hit = _scan_forbidden(str(c.get("clue", "")) + str(c.get("note", "")))
        if hit:
            err(p, f"금지 속성 단서: {', '.join(hit)} — RULES-DO-NOT 위반")

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
    tot_posts = tot_clue = 0
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
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
