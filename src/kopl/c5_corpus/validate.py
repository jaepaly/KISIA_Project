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

# label-schema.md §5-3 — 단서가 실릴 텍스트 채널.
# 캡션은 한 글에 여러 개라 고정 목록으로 닫을 수 없어 정규식으로 강제한다.
TEXT_ID_RE = re.compile(r"^(title|body|profile_bio|photo_caption:\d+)$")
# profile_bio 는 글이 아니라 사용자에 속한다 → post 가 null 이어야 한다
USER_SCOPED_TEXT_IDS = ("profile_bio",)

# card_binding 예약 키. 「어느 카드도 정하지 않는다 — 인물이 스스로 정했다」는 선언.
# 카드와 어긋나는 것이 의도인 축을 여기 적으면 대조에서 빠지고,
# 인물 간 분기 계수에는 그대로 들어간다 (개인차 축이므로 달라야 한다).
FREE_AXIS_KEY = "—"

# §9-1 본문 밖 단서 할당량. 인물 5명 묶음마다 채널별 최소 건수.
OFF_BODY_CHANNELS = ("title", "photo_caption", "profile_bio")
OFF_BODY_QUOTA_PER = 2
QUOTA_GROUP_SIZE = 5

# RULES-DO-NOT: 방어 도구가 민감 속성 추론을 학습하면 그 자체가 무기가 된다.
FORBIDDEN_TERMS = (
    "학력", "학벌", "전공", "졸업", "학번", "수능", "편입",
    "정치", "지지율", "보수", "진보", "투표",
    "건강", "지병", "진단", "복용", "수술", "우울", "장애",
    # ⚠️ 「미사」는 넣지 않는다. 「미사용」(우리가 카드 얘기에 늘 쓰는 말 —
    #    D06·D08 design_note · README · corpus-audit.md)과 하남시 미사1~3동
    #    (data/dict/admin 정본)이 통째로 걸린다. 예외로 빼기에는 지명이 남는다.
    "아이큐", "지능", "종교", "교회", "성당", "절에", "사찰", "예배",
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
# 어느 축을 카드에서 물려받았는지는 **인물이 선언한다** (`card_binding`).
# 카드마다 대표 발견(⭐)이 다르므로 키 이름을 코드에 박아둘 수 없다.
# 예) S13 의 ⭐ 는 「길이 편차」이지 「35자」가 아니고, S15 의 ⭐ 는 「방언」이다.
# card_binding 이 없는 인물은 아래 폴백을 쓰되 선언을 권한다.
FALLBACK_CARD_BOUND = ("종결어미", "격식", "톤", "말투")
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


VOICE_AXES_RE = re.compile(r"<!--\s*voice-axes(.*?)-->", re.S)
UNSPECIFIED = ("—", "-", "", "미상")


def load_card_axes(cards_dir) -> dict:
    """카드의 <!-- voice-axes --> 블록을 읽는다.

    카드 산문은 형식이 제각각이라 기계가 못 읽는다. 그래서 대조할 축만 블록으로 추린다.
    산문 본문이 정본이고 블록은 그 요약이다.
    """
    from pathlib import Path

    out: dict[str, dict] = {}
    d = Path(cards_dir)
    if not d.is_dir():
        return out
    for f in sorted(d.glob("S*.md")):
        sid = f.name.split("_")[0]
        m = VOICE_AXES_RE.search(f.read_text(encoding="utf-8-sig"))
        if not m:
            continue
        axes = {}
        for line in m.group(1).splitlines():
            if ":" not in line or line.strip().startswith("기계 대조용"):
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v not in UNSPECIFIED:
                axes[k] = v
        out[sid] = axes
    return out


NUM_RE = re.compile(r"\d+")
AVG_RE = re.compile(r"평균\s*(\d+)")


def _as_number(val, prefer_avg: bool = False):
    """문자열에서 대표 수치를 뽑는다.

    카드는 「35」 「30~40」 「200 (꼬리 600)」 처럼 쓰고
    인물은 「평균 28자. 최소 8자 ~ 최대 70자」 처럼 쓴다.
    인물 쪽은 「평균 N」 을 우선한다 — 뒤에 오는 최소·최대는 목표값이 아니다.
    """
    t = str(val)
    if prefer_avg:
        m = AVG_RE.search(t)
        if m:
            return float(m.group(1))
    nums = [float(x) for x in NUM_RE.findall(t)]
    if not nums:
        return None
    # 「30~40」 같은 범위는 중앙값. 「200 (꼬리 600)」 은 앞의 것이 기본값
    if "~" in t.split("(")[0] and len(nums) >= 2:
        return (nums[0] + nums[1]) / 2
    return nums[0]


def _numeric_axis(card_val) -> bool:
    """카드 값이 수치인가. 앞부분이 숫자로 시작하면 수치 축으로 본다."""
    return bool(re.match(r"^\s*\d", str(card_val)))


def _covers(persona_val, card_val) -> float:
    """카드 값이 인물 값 안에 들어 있는가 (포함 계수).

    인물은 카드를 그대로 옮기지 않고 부연한다 —
    카드 「한 줄에 2~4어절」 → 인물 「모바일 에디터식 짧은 줄바꿈. 한 줄에 2~4어절」.
    자카드로 재면 부연할수록 점수가 떨어져 오탐이 난다.
    """
    a, b = _bigrams(persona_val), _bigrams(card_val)
    if not a or not b:
        return 0.0
    base = len(a & b) / min(len(a), len(b))
    # 종결어미는 카드가 성격을("존댓말 정보 공유체") 인물이 형태를("~해요체") 적어
    # 같은 뜻인데 글자가 다르다. ~로 시작하는 어미 토큰을 따로 대조해 보정한다.
    # "~해요체" 와 "~해요" 가 같은 것을 가리키므로 접미 「체/형」을 떼고 비교한다
    norm = lambda xs: {re.sub(r"(체|형)$", "", x) for x in xs}
    ta = norm(re.findall(r"~\w+", str(persona_val)))
    tb = norm(re.findall(r"~\w+", str(card_val)))
    if ta and tb:
        base = max(base, len(ta & tb) / min(len(ta), len(tb)))
    return base


def card_check(personas: list[tuple[str, dict]], card_axes: dict) -> list[str]:
    """인물의 voice 가 물려받기로 한 카드와 맞는지 본다.

    기본은 card_ref 첫 카드가 이긴다. card_binding 에 적으면 그쪽이 이긴다.
    """
    lines: list[str] = []
    for pid, d in personas:
        refs = d.get("card_ref", []) or []
        if not refs:
            continue
        binding = d.get("card_binding") or {}
        # 축 → 어느 카드를 따르나
        gov: dict[str, str] = {}
        free: set = set()
        for card, axes in binding.items():
            if card == FREE_AXIS_KEY:
                free |= set(axes)
                continue
            for ax in axes:
                gov[ax] = card
        voice = d.get("voice") or {}
        rows = []
        for ax, val in sorted(voice.items()):
            if ax in free:                       # 카드를 따르지 않기로 선언한 축
                rows.append(f"      --  {ax:10} {'(카드 없음)':14} 인물이 정함")
                continue
            card = gov.get(ax, refs[0])          # 미지정이면 첫 카드
            target = (card_axes.get(card) or {}).get(ax)
            if target is None:
                if ax in gov:
                    # 명시적으로 묶었는데 그 카드에 그 축이 없다.
                    # 카드가 안 규정했거나, 축 이름이 카드 블록과 다르거나.
                    rows.append(f"      ?   {ax:10} {card:14} 그 카드에 이 축이 없다 — 대조 불가")
                continue                          # 카드가 그 축을 규정하지 않았다
            if _numeric_axis(target):
                pv = _as_number(val, prefer_avg=True)
                cv = _as_number(target)
                if pv is None or not cv:
                    mark, extra = "?  ", "  ← 인물 값에서 수치를 못 읽음"
                else:
                    dev = abs(pv - cv) / cv
                    mark = "OK " if dev <= 0.25 else ("△  " if dev <= 0.5 else "✗  ")
                    extra = f"  (인물 {pv:g} · 편차 {(pv - cv) / cv * 100:+.0f}%)"
            else:
                sim = _covers(val, target)
                mark = "OK " if sim >= 0.5 else ("△  " if sim >= 0.15 else "✗  ")
                extra = ""
            src = f"{card}{'' if ax in gov else ' (첫 카드)'}"
            rows.append(f"      {mark} {ax:10} {src:14} 카드 「{target}」{extra}")
        if rows:
            lines.append(f"  {pid}  card_ref={refs}")
            lines += rows
    return lines


def _bound(persona: dict, card: str) -> set:
    """이 인물이 그 카드에서 물려받았다고 선언한 축.

    예약 키(FREE_AXIS_KEY)에 적힌 축은 어느 카드도 정하지 않은 것이므로
    카드 축이 아니다 — 인물 간 분기 계수에 그대로 들어간다.
    """
    if card == FREE_AXIS_KEY:
        return set()
    return set((persona.get("card_binding") or {}).get(card, []))


def _gov(persona: dict) -> dict:
    """축 → 그 축을 정한 카드. card_binding 에 명시된 것만 본다."""
    out = {}
    for card, axes in (persona.get("card_binding") or {}).items():
        for ax in axes:
            out[ax] = card
    return out


def cross_check(personas: list[tuple[str, dict]]) -> list[str]:
    """카드를 공유하는 인물끼리 목소리가 갈리는지 본다.

    카드 축(둘 다 같은 카드에 명시적으로 묶은 축)은 겹치는 게 정상이라 계수에서 빼되,
    값이 다르면 한쪽이 카드를 안 따른 것이므로 경고한다.
    한 쌍은 공유 카드가 몇 장이든 **한 번만** 비교한다.
    """
    pairs: dict[tuple[str, str], tuple] = {}
    for i in range(len(personas)):
        for j in range(i + 1, len(personas)):
            (pa, a), (pb, b) = personas[i], personas[j]
            shared = sorted(set(a.get("card_ref") or []) & set(b.get("card_ref") or []))
            if shared:
                pairs[(pa, pb)] = (a, b, shared)

    lines: list[str] = []
    for (pa, pb), (a, b, shared) in pairs.items():
        va, vb = a.get("voice") or {}, b.get("voice") or {}
        ga, gb = _gov(a), _gov(b)
        declared = bool(ga or gb)

        rows, distinct, bound_n = [], 0, 0
        for k in sorted(set(va) & set(vb)):
            sim = _similarity(va[k], vb[k])
            if declared:
                # 둘 다 같은 카드에 명시적으로 묶은 축만 카드 축이다.
                # 예약 키(자유 축)나 한쪽만 묶은 축은 인물 축으로 센다.
                is_bound = (k in ga and k in gb
                            and ga[k] == gb[k] and ga[k] != FREE_AXIS_KEY)
            else:
                is_bound = any(t in k for t in FALLBACK_CARD_BOUND)
            if is_bound:
                bound_n += 1
                # 수치 축은 숫자로 본다. 둘 다 같은 카드를 따르되 허용 범위 안의
                # 다른 지점에 있을 수 있다 (카드 40자 → 인물 32자·48자)
                # 카드 대비 ±25% 를 각자 허용하므로 둘 사이는 최대 40% 벌어질 수 있다.
                # 카드와의 일치는 card_check 가 이미 본다. 여기서는 같은 밴드인지만 본다.
                na, nb = _as_number(va[k], True), _as_number(vb[k], True)
                if na and nb:
                    sim = 1.0 if abs(na - nb) / max(na, nb) <= 0.45 else 0.0
                if sim < VOICE_SIM_THRESHOLD:
                    rows.append(f"      {k:12} {sim:.2f}  ⚠ 같은 카드에 묶었는데 값이 다르다")
                else:
                    src = ga.get(k, "폴백")
                    rows.append(f"      {k:12} {sim:.2f}  (카드 축 {src})")
            elif sim < VOICE_SIM_THRESHOLD:
                distinct += 1
                rows.append(f"      {k:12} {sim:.2f}  다름")
            else:
                rows.append(f"      {k:12} {sim:.2f}  ⚠ 겹침")

        ta = a.get("noise_topics") or (va.get("소재") or [])
        tb = b.get("noise_topics") or (vb.get("소재") or [])
        if ta and tb:
            sim = _similarity(ta, tb)
            if sim < VOICE_SIM_THRESHOLD:
                distinct += 1
            rows.append(f"      {'소재':12} {sim:.2f}  "
                        f"{'다름' if sim < VOICE_SIM_THRESHOLD else '⚠ 겹침'}")

        total = len(rows) - bound_n
        ok = distinct >= min(MIN_DISTINCT_AXES, total)
        tag = "" if declared else "  (card_binding 미선언 — 폴백 적용)"
        lines.append(f"  {pa} ↔ {pb}  공유 카드 {','.join(shared)}{tag}")
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


# 금지어를 부분 문자열로 찾으면 무해한 낱말이 걸린다.
# 「어절에」·「계절에」가 "절에"(종교)로, 「장애물」이 "장애"(건강)로 잡혔다.
# 노이즈 소재까지 전역 스캔하므로 날씨 얘기에 「계절」만 나와도 걸린다.
# 스캔 전에 아래 낱말을 지운다. 금지어 목록 자체는 건드리지 않는다.
#
# ⚠️ 「보수」(정치/수리/급여)와 「관절」(일상/건강)은 일부러 넣지 않았다.
#    실제로 뜻이 갈려서 사람이 봐야 한다 — WARN 으로 남는 게 맞다.
FORBIDDEN_EXCEPTIONS = ("어절", "계절", "예절", "조절", "절약", "명절", "장애물")


def _scan_forbidden(text: str) -> list[str]:
    for safe in FORBIDDEN_EXCEPTIONS:
        text = text.replace(safe, "")
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
    # profile_bio 단서는 글에 실리지 않으므로 post_plan 산술에서 제외한다
    post_clues = [c for c in clue_plan if c.get("text_id") not in USER_SCOPED_TEXT_IDS]
    # 한 글이 본문·제목·캡션에 각각 단서를 가질 수 있으므로 항목 수가 아니라 글 수로 센다
    clue_posts = {c.get("post") for c in post_clues}
    if len(clue_posts) != parts["clue"] + parts["trap"]:
        err(
            "clue_plan",
            f"단서를 가진 글 {len(clue_posts)}편 ≠ post_plan의 "
            f"clue({parts['clue']})+trap({parts['trap']})",
        )

    # ── clue_plan 각 항목 ─────────────────────────────────────────────
    seen: dict[str, str] = {}
    for i, c in enumerate(clue_plan):
        p = f"clue_plan[{i}]"
        post = c.get("post", "")
        if post is None:
            pass   # profile_bio 단서 — 글에 속하지 않는다
        elif not POST_ID_RE.match(str(post)):
            err(p, f"post={post!r} — b01 형식이어야 한다")
        else:
            # attr 까지 키에 넣는다. 스팬 하나가 여러 속성을 동시에 실을 수 있다 —
            # S11 의 「늙은 홀아비」는 한 어절에 연령·성별·혼인상태가 겹친다.
            # (post, text_id) 만으로 키를 잡으면 그 형태를 아예 쓸 수 없었다.
            key = f"{post}/{c.get('text_id', 'body')}/{c.get('attr')}"
            if key in seen:
                err(p, f"{key} 가 {seen[key]} 와 중복")
            else:
                seen[key] = p
        if total and post and POST_ID_RE.match(str(post)) and int(post[1:]) > total:
            err(p, f"post={post} 가 total({total})을 넘는다")

        tid = c.get("text_id", "body")   # 미지정은 본문으로 본다 (하위호환)
        if not TEXT_ID_RE.match(str(tid)):
            err(p, f"text_id={tid!r} — body/title/profile_bio/photo_caption:N 중 하나 "
                   f"(label-schema §5-3)")
        elif tid in USER_SCOPED_TEXT_IDS and c.get("post") is not None:
            err(p, f"text_id={tid} 는 사용자 단위다. post 는 null 이어야 한다")
        elif tid not in USER_SCOPED_TEXT_IDS and c.get("post") is None:
            err(p, f"text_id={tid} 는 글 단위다. post 가 필요하다")

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
        if any(k.startswith(f"{post}/") for k in seen):
            err("ambient_plan.posts", f"{post} 가 clue_plan에도 있다")
    if len(ambient) != parts["ambient"]:
        err("ambient_plan.posts", f"{len(ambient)}개 ≠ post_plan.ambient({parts['ambient']})")

    # 노이즈 비율 B안: 단서 보유 편수(clue+trap) 기준
    if total:
        noise = 1 - len(clue_posts) / total
        lo, hi = PERSONA_NOISE_BAND
        if not lo <= noise <= hi:
            warn(
                "post_plan",
                f"노이즈 {noise:.0%} — 인물 밴드 {lo:.0%}~{hi:.0%} 밖. "
                f"참조 카드의 노이즈 목표와 맞는지 확인",
            )

    # ── card_binding (persona-design.md §2-⑤-3) ──────────────────────
    cb = persona.get("card_binding")
    refs = persona.get("card_ref", []) or []
    if cb is None:
        # 카드가 한 장이면 바인딩할 것이 없다 — 「첫 카드가 이긴다」가 곧 전부다.
        # 여기서 경고하면 단일 카드 인물 전원이 걸려 진짜 미배정 경고가 묻힌다.
        if len(refs) > 1:
            warn("card_binding",
                 f"카드를 {len(refs)}장 참조하는데 어느 카드에서 어느 축을 물려받았는지 "
                 "선언되지 않았다. 카드를 공유하는 인물끼리 대조할 때 폴백 규칙"
                 "(card_ref 첫 카드가 이긴다)이 적용된다")
    elif not isinstance(cb, dict):
        err("card_binding", "객체여야 한다 — {\"S13\": [\"글길이\"], ...}")
    else:
        for card, axes in cb.items():
            if card == FREE_AXIS_KEY:
                continue
            if card not in refs:
                err(f"card_binding.{card}",
                    f"card_ref 에 없는 카드다. 참조하지 않은 카드에서 축을 물려받을 수 없다")
            if not isinstance(axes, list) or not all(isinstance(x, str) for x in axes):
                err(f"card_binding.{card}", "문자열 배열이어야 한다")

        # 바인딩한 축 이름이 인물 voice 키와 맞는지 본다.
        # 안 맞으면 그 바인딩은 조용히 아무 일도 안 한다 — 축을 못 찾으니
        # 폴백(첫 카드)이 그 축을 가져간다. 작성자는 배정했다고 믿는다.
        #
        # 실측 2026-08-28 (#95): 카드 축은 「오타」인데 인물 키는 「오타율」이라
        # {"S8": ["오타"]} 가 통째로 무시됐다. 축 이름이 카드 쪽과 인물 쪽
        # 두 벌이라 생기는 문제다(#78 에서 지적, W3 정리 예정).
        vkeys = set((persona.get("voice") or {}).keys())
        for card, axes in cb.items():
            if not isinstance(axes, list):
                continue
            for ax in axes:
                if not isinstance(ax, str) or ax in vkeys:
                    continue
                near = [k for k in vkeys if k.startswith(ax) or ax.startswith(k)]
                hint = f" (「{near[0]}」 인 듯하다)" if near else ""
                warn(f"card_binding.{card}",
                     f"「{ax}」 는 이 인물의 voice 에 없는 축이다. "
                     f"이 바인딩은 아무 일도 하지 않고 폴백이 적용된다.{hint}")
        # 참조만 하고 축을 하나도 안 물려받은 카드를 찾는다.
        # 첫 카드는 폴백으로 나머지 축을 전부 가져가므로 유휴가 아니다.
        # FREE_AXIS_KEY 는 카드가 아니므로 세지 않는다 — 세면 "2장 참조인데
        # 2장에만 배정했다" 같은 모순된 문구가 나온다.
        if len(refs) > 1:
            bound = {k for k in cb if k != FREE_AXIS_KEY}
            idle = [c for c in refs[1:] if c not in bound]
            if idle:
                warn("card_binding",
                     f"{', '.join(idle)} 을(를) card_ref 에 두었는데 물려받은 축이 없다. "
                     f"폴백으로 첫 카드({refs[0]})가 나머지를 전부 가져간다 — "
                     "참조만 하고 안 쓸 거면 card_ref 에서 빼는 편이 낫다")

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
    cards_dir = None
    if "--cards" in argv:
        i = argv.index("--cards")
        cards_dir = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
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
        tot_clue += len({
            c.get("post") for c in d.get("clue_plan", []) or []
            if c.get("text_id") not in USER_SCOPED_TEXT_IDS
        })
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

    # ── §9-1 본문 밖 단서 할당량 ─────────────────────────────────────
    # "인물 5명 묶음마다 채널별 2건 이상". 5명 미만이면 비례로 환산해 진척만 보여준다.
    if loaded:
        chan: dict[str, int] = {c: 0 for c in OFF_BODY_CHANNELS}
        for _, d in loaded:
            for c in d.get("clue_plan", []) or []:
                tid = str(c.get("text_id", "body"))
                if tid.startswith("photo_caption"):
                    chan["photo_caption"] += 1
                elif tid in chan:
                    chan[tid] += 1
        groups = len(loaded) / QUOTA_GROUP_SIZE
        need = OFF_BODY_QUOTA_PER * groups
        print(f"\n[본문 밖 단서 — §9-1] 인물 {len(loaded)}명 "
              f"(5명 묶음 {groups:.1f}개 · 채널별 {need:.1f}건 필요)")
        short = False
        for c in OFF_BODY_CHANNELS:
            ok = chan[c] >= need
            if not ok:
                short = True
            print(f"  {'OK ' if ok else '⚠  '} {c:16} {chan[c]}건")
        if short:
            print("  → clue_plan 에 text_id 를 지정해 배치할 것. "
                  "본문만 스캔하는 도구가 못 잡는 지점이라 「추가 탐지율」의 근거가 된다")

    if cards_dir:
        ca = load_card_axes(cards_dir)
        if not ca:
            print(f"\n(카드 블록을 못 읽었다: {cards_dir})")
        else:
            rows = card_check(loaded, ca)
            if rows:
                print(f"\n[카드 대조 — 카드 {len(ca)}장]  "
                      f"OK 일치 · △ 부분 일치 · ✗ 어긋남")
                print("\n".join(rows))
                if any(r.strip().startswith("✗") for r in rows):
                    print("      ✗ 는 카드를 안 따랐다는 뜻이다. "
                          "의도한 것이면 card_binding 에 다른 카드를 적어라")

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
