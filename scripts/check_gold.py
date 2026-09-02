"""라벨(gold/detect/design) jsonl 파일을 §11 규칙 1~14로 검사한다.

    python scripts/check_gold.py data/corpus/v0/gold/detect/*.jsonl
    python scripts/check_gold.py data/corpus/v0/gold/               (디렉터리째)
    python scripts/check_gold.py data/corpus/v0/gold/D06_spans.jsonl --strict

label-schema.md §11 이 1~14번은 "라벨 검증기"가 맡는다고 못박아뒀는데,
그 검증기가 저장소에 없었다. label.py 의 finalize() 가 생성 시점 검증을
하지만, 그 뒤 사람이 검수하며 손으로 고친 파일은 아무도 안 본다.
이 스크립트가 그 자리를 메운다 — label.py 출력이든, 검수 후 손으로 고친
파일이든 똑같이 돌릴 수 있다.

15·16번(인물 5명 묶음 할당량)은 여기서 안 본다 — validate.py 몫이다.

--strict 를 주면 WARN 도 실패로 친다 (exit code 1). 기본은 ERROR 만 실패로 친다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# label-schema.md §3-2 정본의 복사본이다. 여기가 갈라지면 §3-2 를 따른다.
TYPES = {"AGE", "SEX", "LOC_ADMIN", "LOC_FACILITY", "REL_HOME",
         "REL_WORK", "JOB", "FAM", "COMMUTE", "INCOME"}
LEVELS = {"explicit", "implicit", "inferential"}
SUBJECTS = {"self", "other", "unknown"}
TEXT_ID_RE = re.compile(r"^(title|body|profile_bio|photo_caption:\d+)$")
SPAN_FIELDS = {"span_id", "text_id", "start", "end", "text", "type", "level", "subject"}


class Result:
    def __init__(self, path: str):
        self.path = path
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, rule: str, msg: str):
        self.errors.append(f"[{rule}] {msg}")

    def warn(self, rule: str, msg: str):
        self.warnings.append(f"[{rule}] {msg}")

    @property
    def ok(self) -> bool:
        return not self.errors


def is_nfc(s: str) -> bool:
    return unicodedata.normalize("NFC", s) == s


def check_span(sp: dict, texts: dict, seen_ids: set, r: Result, where: str):
    span_id = sp.get("span_id")

    # 규칙 11 — 8필드 외에 없음 (score 는 모델 출력에만, 골드에는 없음)
    extra = set(sp.keys()) - SPAN_FIELDS
    if "score" in extra:
        extra.discard("score")
        r.err("11·12", f"{where} {span_id}: score 필드가 있다 (골드셋엔 없어야 함)")
    if extra:
        r.err("11", f"{where} {span_id}: 8필드 외 필드 {sorted(extra)}")
    missing = SPAN_FIELDS - set(sp.keys())
    if missing:
        r.err("11", f"{where} {span_id}: 필드 누락 {sorted(missing)}")
        return  # 이후 검사는 필드가 있어야 의미가 있다

    # 규칙 12 — score 범위 (있으면. 골드엔 원래 없어야 하지만 있다면 범위는 봐준다)
    if "score" in sp:
        sc = sp["score"]
        if not isinstance(sc, (int, float)) or not (0 <= sc <= 1):
            r.err("12", f"{where} {span_id}: score={sc} 가 [0,1] 밖")

    # 규칙 1·2·3 — enum
    if sp.get("type") not in TYPES:
        r.err("1", f"{where} {span_id}: type={sp.get('type')!r} 이 10종 enum 밖")
    if sp.get("level") not in LEVELS:
        r.err("2", f"{where} {span_id}: level={sp.get('level')!r} 이 enum 밖")
    if sp.get("subject") not in SUBJECTS:
        r.err("3", f"{where} {span_id}: subject={sp.get('subject')!r} 이 enum 밖")

    # 규칙 4 — text_id 형식
    tid = sp.get("text_id")
    if not isinstance(tid, str) or not TEXT_ID_RE.match(tid):
        r.err("4", f"{where} {span_id}: text_id={tid!r} 가 패턴에 안 맞음")
        return

    # 규칙 10-b — text_id 가 실제 texts 채널에 있음
    if tid not in texts:
        r.err("10-b", f"{where} {span_id}: text_id={tid} 가 이 글의 texts 에 없음")
        return

    hay = texts[tid]

    # 규칙 7 — offset 범위
    s, e = sp.get("start"), sp.get("end")
    if not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e <= len(hay)):
        r.err("7", f"{where} {span_id}: offset [{s},{e}) 가 0≤start<end≤len({len(hay)}) 밖")
        return

    # 규칙 5 — text == texts[text_id][start:end]
    if sp.get("text") != hay[s:e]:
        r.err("5", f"{where} {span_id}: text={sp.get('text')!r} != 원문[{s}:{e}]={hay[s:e]!r}")

    # 규칙 6 — NFC
    if not is_nfc(sp.get("text", "")):
        r.err("6", f"{where} {span_id}: text 가 NFC 정규화 안 됨")

    # 규칙 9 — span_id 파일 내 유일
    if span_id in seen_ids:
        r.err("9", f"{where}: span_id={span_id} 중복")
    seen_ids.add(span_id)


def check_overlap(spans: list[dict], r: Result, where: str):
    # 규칙 8 — 같은 text_id 안에서만 겹침 검사
    by_tid: dict[str, list[dict]] = {}
    for sp in spans:
        by_tid.setdefault(sp.get("text_id"), []).append(sp)
    for tid, group in by_tid.items():
        group = sorted(group, key=lambda s: (s.get("start", 0), s.get("end", 0)))
        for a, b in zip(group, group[1:]):
            if a.get("end", -1) > b.get("start", 0):
                r.err("8", f"{where} {tid}: {a.get('span_id')} 와 {b.get('span_id')} 가 겹침")


def check_file(path: Path, r: Result):
    lines = [l for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    if not lines:
        r.err("13", "빈 파일")
        return

    # 규칙 13 — 첫 줄 schema_version 헤더
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError:
        r.err("13", "첫 줄이 JSON 이 아니다")
        return
    if "schema_version" not in header or "post_id" in header or "spans" in header:
        r.err("13", "첫 줄이 schema_version 헤더가 아니다 (post_id/spans 가 있으면 헤더가 아니라 레코드다)")

    seen_span_ids: set[str] = set()

    for i, line in enumerate(lines[1:], 2):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            r.err("구조", f"{i}번째 줄 JSON 파싱 실패: {e}")
            continue

        is_profile = "post_id" not in rec and "profile_bio" in rec

        if is_profile:
            # 사용자 단위 레코드 (§8-4) — profile_bio 스팬은 여기에만 있어야 한다 (규칙 10)
            where = f"{rec.get('persona_id', '?')}_bio"
            texts = {"profile_bio": rec.get("profile_bio", "")}
            spans = rec.get("spans", [])
            for sp in spans:
                check_span(sp, texts, seen_span_ids, r, where)
            check_overlap(spans, r, where)
            if "reviewed" not in rec:
                r.err("14", f"{where}: reviewed 필드가 없다")
            continue

        # 글 레코드
        post_id = rec.get("post_id", f"line{i}")
        where = post_id
        texts = rec.get("texts") or {}
        spans = rec.get("spans", [])

        # 규칙 10 — profile_bio 스팬이 글 레코드 안에 있으면 안 된다
        for sp in spans:
            if sp.get("text_id") == "profile_bio":
                r.err("10", f"{where}: profile_bio 스팬이 글 레코드에 있다 (사용자 레코드로 옮겨야 함)")

        for sp in spans:
            check_span(sp, texts, seen_span_ids, r, where)
        check_overlap(spans, r, where)

        # 규칙 6 — texts 채널 자체도 NFC
        for tid, txt in texts.items():
            if not is_nfc(txt):
                r.err("6", f"{where}: texts[{tid}] 가 NFC 정규화 안 됨")

        # 규칙 14 — spans:[] 인 글도 reviewed 가 있어야 한다
        if "reviewed" not in rec:
            r.err("14", f"{where}: reviewed 필드가 없다")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="jsonl 파일 또는 디렉터리")
    ap.add_argument("--strict", action="store_true", help="WARN 도 실패로 친다")
    a = ap.parse_args()

    files: list[Path] = []
    for p in a.paths:
        pp = Path(p)
        if pp.is_dir():
            files += sorted(pp.rglob("*_spans.jsonl"))
        else:
            files.append(pp)

    if not files:
        print("검사할 파일이 없다"); return 2

    any_error = any_warn = False
    for f in files:
        r = Result(str(f))
        try:
            check_file(f, r)
        except Exception as e:  # noqa: BLE001
            r.err("구조", f"검사 중 예외: {e}")

        if r.errors or r.warnings:
            print(f"■ {f}")
            for e in r.errors:
                print(f"  ✗ {e}")
            for w in r.warnings:
                print(f"  ⚠ {w}")
        else:
            print(f"✓ {f}")

        any_error = any_error or bool(r.errors)
        any_warn = any_warn or bool(r.warnings)

    print()
    if any_error or (a.strict and any_warn):
        print("검증 실패 — 위 ✗ 항목을 고쳐야 한다")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
