# 파도풀 — 공개 게시글 누적·결합에 따른 재식별 위험 자가진단 및 보호조치 추천 시스템

KISIA 2026 AI 보안기술개발 · 개인정보 트랙 3팀 · 2026-08-17 ~ 11-06 (12주) · 담당 멘토 권영길

> 흩어진 글이 쌓이고 서로 결합하면서 발생하는 재식별 위험을 진단하고,
> **가장 적은 부담으로 되돌릴 수 있는 조치를 추천**한다. 탐지는 **외부 전송 없이 이용자 기기에서** 수행한다.

---

> ## 📌 이 문서는 **이번 주에 할 일**만 다룬다
>
> | 찾는 것 | 문서 |
> |---|---|
> | **이번 주 내가 뭘 해야 하나** | **여기 (아래)** |
> | 내 역할 전체 (12주) | [docs/roles/](docs/roles/) |
> | 프로젝트가 뭔지 | [docs/overview.md](docs/overview.md) |
> | 계획 전문 | [docs/plan.md](docs/plan.md) |
> | 주차별 일정·게이트 | [docs/roadmap.md](docs/roadmap.md) |
> | 협업 규칙 (브랜치·커밋·리뷰) | [CONTRIBUTING.md](CONTRIBUTING.md) |
> | **골드셋 형식** | [docs/contracts/label-schema.md](docs/contracts/label-schema.md) §8 · §9 |
> | **절대 하면 안 되는 것** | [docs/RULES-DO-NOT.md](docs/RULES-DO-NOT.md) |
> | **팀 대시보드** | http://52.79.198.223/ (AWS) |

---

## 지금 상태

**W5 주요 성과 완료 · W6 진입 (추석 연휴 9/24~27 · 근무일 월~수)** — `w05` 태그 완료 (9/22 · #268 머지 커밋 `c792573`) → [compare w04...w05](../../compare/w04...w05)

| 항목 | W5 끝 |
|---|---|
| 코퍼스 | **v1 동결** ✅ 115명 3,092편 · d4cf8cb · 9/9 |
| 골드셋 검수 | **417편 587스팬** ✅ + blind 159편 267스팬 (#229 · 9/14) |
| IAA | **2차 완료 ✅** overall 50.0% (explicit 51.9% · implicit 44.4% · inferential 20.0% · 9/17) |
| 1단 탐지 v1 | **koelectra-v1 확정 ✅** checkpoint-epoch-10 · test F1 0.2940 · p95 276ms (#263 · 9/18) |
| 2단 QLoRA | **3ep adapter v1 확정 ✅** dev_loss 0.0044 · verdict 90% (#264 · 9/18) |
| 기여도 엔진 | **LOO v1 ✅** loo.py · CI pass (#251 · 9/16) · `risk_total` PR #268 수정 대기 |
| 분석 웹앱 | **3화면 연결 ✅** ENGINE_MODE=mock 엔드투엔드 에러 없음 (#254 · 9/17) |
| 지명 사전 | UNKNOWN 18→2 ✅ · 픽스처 19/19 (#218) |
| 가명화·복원 | `anonymize()` + `restore()` ✅ 라운드트립 15종 (#243 · 9/14) |
| 설계서 | ✅ 제출 완료 9/10 |
| `w04` 태그 | ✅ 9/11 · `w05` 태그 — C 증류 타깃 PR 머지 후 |

| 역할 | 담당 | **이번 주 핵심** |
|---|---|---|
| **[A · 데이터 리드](docs/roles/A-data.md)** | 이은선 | 문서 정비 (decisions.md 최신화) — 비동기 |
| **[B · 1단 탐지](docs/roles/B-detector.md)** | 최진필 | E real.py 연결 준비 — 체크포인트·임계값 공유 |
| **[C · 특정성·누적](docs/roles/C-specificity.md)** | 신정현 | **증류 타깃 세트** — PR #268 clamp + span_to_condition() + gen_contribution_targets.py |
| **[D · 2단 추론·조치](docs/roles/D-stage2.md)** | 박재현 (PM) | 월 KISIA 줌 발표 · w05 태그 |
| **[E · 시스템·컴플라이언스](docs/roles/E-system.md)** | 이지희 | **활동 메타 필드** — 공개/비공개 토글 |

---

# W6 (9/21~9/27) — 각자 할 일

**제출물**: 주간활동보고서 (외부)
**단계**: **M2-c** · 근무일 3일 🔴 — **월 9/21 · 화 9/22 · 수 9/23** (추석 연휴 목 9/24 ~ 일 9/27)

> ## 이번 주 한 문장 — **C가 증류 타깃을 완성하고, E가 활동 메타를 채운다. 마감은 수요일.**
>
> 로드맵 §3:
>
> W6은 추석 연휴로 근무일이 **월·화·수 3일**뿐이다. B·D 학습 잡은 이미 확정(불필요)이라 비동기. 핵심은 C가 #261 결정을 구현해 증류 타깃 PR을 올리는 것, E가 활동 메타의 남은 조각(시딩 위치태그·프로필 시간대 분포)을 채우는 것이다. **내부 마감은 수 9/23 23:59.** 수요일까지 안 끝나는 것은 연휴 뒤 월 9/28로 넘긴다 — 연휴 중 작업을 기대하지 않는다.

---

## 0. 전원 공통 — 월 9/21 11:15 KISIA 줌 주간보고회

D(PM)이 W5 성과를 발표한다. 개인 5줄 보고를 **일요일 9/20 저녁까지** PM에게 보낸다.

```
1. 이번 주 내 목표:
2. 실제로 한 일:
3. 달라진 것 (before → after, 숫자):
4. 증빙 링크:
5. 막힌 것 + 필요한 지원:
```

**D가 발표할 W5 요약:**

| 역할 | W5 핵심 성과 |
|---|---|
| B | koelectra-v1 확정 · test F1 0.2940 · p95 276ms |
| D | Qwen3 3ep adapter v1 확정 · verdict 90% |
| C | LOO 기여도 엔진 v1 완성 · IAA 2차 50.0% |
| E | 분석 웹앱 3화면 연결 · 수동 업로드 경로 |
| A | 라벨 품질관리 · 네거티브 보강 · label-schema §4-1 나이 어미 경고 |

---

## W5 이월 항목

| 항목 | 담당 | 상태 |
|---|---|---|
| PR #268 `risk_total` clamp 수정 | C | **머지 완료** (9/22 · [#268](../../pull/268)) |
| #261 span_to_condition() 구현 | C | **W6 핵심** — clues.py → C3 어댑터 → 증류 타깃 PR |
| w05 태그 | D(PM) | **완료** (9/22 · `c792573` · [compare](../../compare/w04...w05)) |
| 활동 메타 — 남은 조각 | E | 스키마·토글·표시는 W3에 끝남. **시딩 위치태그 · 프로필 시간대 분포**가 남았다 |

---

## 전원 공통 — 주간보고서 (수 9/23 23:59)

근무일이 3일뿐이라 내부 마감을 수요일로 당긴다. 원고는 드라이브 — PM(재현)에게 **수 9/23 23:59** 까지.

```
1. 이번 주 내 목표:
2. 실제로 한 일:
3. 달라진 것 (before → after, 숫자):
4. 증빙 링크:
5. 막힌 것 + 필요한 지원:
```

---

## A · 이은선 — 문서 정비 (비동기)

> 전체 매뉴얼 [docs/roles/A-data.md](docs/roles/A-data.md)

W6 A 역할은 연휴 비동기. 시간이 날 때 아래를 처리한다.

### decisions.md 최신화

W5에서 확정된 결정을 [docs/decisions.md](docs/decisions.md)에 추가한다.

- #261 스팬→condition 변환 규칙 (resolution 산정·subject·REL 처리) — 9/19
- #263 koelectra-v1 체크포인트 확정 (checkpoint-epoch-10·임계값 0.7)
- #264 Qwen3 3ep adapter v1 확정 (verdict 90%)

```bash
# 현재 마지막 DEC 번호 확인
grep "DEC-0" docs/decisions.md | tail -5
```

### (선택) W7 대비 — [docs/roles/A-data.md](docs/roles/A-data.md)

W7 A 역할: "exp8 축약판 지원". 필요한 라벨 추가 작업이 있는지 미리 파악한다.

### 완료 기준

- [ ] decisions.md — W5 결정 3건 추가

---

## B · 최진필 — E 실 엔진 연결 준비 (비동기)

> 전체 매뉴얼 [docs/roles/B-detector.md](docs/roles/B-detector.md) · [howto/b-finetune.md](docs/roles/howto/b-finetune.md)

### 현황

v1 체크포인트 확정 완료 (#263 · 9/18):
- 경로: `experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10`
- 임계값: 0.7 · 내부 eval F1 0.4839 · test F1 0.2940 · p95 276ms
- 학습 잡 비동기 → **불필요 확정** (1ep=16.57초 · #262)

### E에게 infer.py 사용법 공유 (월~화 · 이슈 코멘트 한 개)

E가 W7에 `engines/real.py`를 구현할 때 필요한 정보를 이슈 코멘트로 남긴다. 아래 다섯 줄이면 된다.

```bash
# 1) 체크포인트 — B 데스크톱 로컬. 공유 방법(드라이브 zip / 별도 저장소)은 코멘트에서 정한다
experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10

# 2) 실행 예시 — 플래그명은 --min-span-score (기본값 0.7 · registry 등록값과 같음)
python experiments/exp06-finetune/infer.py \
  --checkpoint-dir experiments/exp06-finetune/runs/v1_lr5e-5/checkpoint-epoch-10 \
  --post '{"post_id":"test","body":"신갈저수지 조황입니다"}' \
  --min-span-score 0.7 --device cpu

# 3) 출력 계약: docs/contracts/span.schema.json  (입력은 infer.py input_channels() 가 받는 post 레코드)
```

**반드시 함께 적을 제한** ([registry.md](models/registry.md) 46~47행): 모델은 **경계·유형만** 예측한다. 출력의 `level=implicit`·`subject=self`는 호환용 고정값이지 판정이 아니다 (`infer.py:27-29`, `resolver` 미지정 시 `RuntimeWarning`). E가 real.py에서 이 값을 그대로 위험도 계산에 넘기면 등급·주체 분기가 전부 무력화되므로, **W7 연결 때 의미 판정 resolver(D 2단 또는 규칙)를 어디서 붙일지 함께 정한다.** C의 `span_to_condition()` 검증도 이 때문에 골드(검수된 level·subject)로 한다.

### 완료 기준

- [ ] E에게 체크포인트 경로·`--min-span-score 0.7`·level/subject 고정값 제한을 이슈 코멘트로 공유 (수 9/23까지)

---

## C · 신정현 — 증류 타깃 세트

> 전체 매뉴얼 [docs/roles/C-specificity.md](docs/roles/C-specificity.md) · [howto/c-engine.md](docs/roles/howto/c-engine.md)

### ⭐ 이번 주 C 의 핵심 — 증류 타깃을 완성한다

이 PR이 머지되면 **w05 태그**를 단다. 근무일 3일이라 순서가 중요하다 — **월 #268 → 월~화 변환기 → 화~수 생성기·PR.** 수요일까지 PR이 안 올라가면 연휴 뒤 월 9/28에 이어서 한다.

```
골드 스팬 (type·level·subject·text)
   │  span_to_condition()          ← 월~화 · clues.py (신규)
   ▼
condition {axis, kind, value|geo_code, resolution, confidence, source_post_ids}
   │  risk_total()                 ← PR #268 (clamp 1건 고치면 머지)
   ▼
0~100 위험도  ──▶  leave_one_out(risk_fn=…)   ← loo.py (이미 머지 #251)
   ▼
data/corpus/v0/gold/contribution/<pid>.json    ← 화~수 · gen_contribution_targets.py (신규)
```

### 월 — PR #268 clamp 수정 재제출

[PR #268 리뷰 (9/19 · CHANGES_REQUESTED)](../../pull/268) 필수 1건: `engine.py:98`이 `specificity.schema.json` 계약상 유효한 `resolution`(정수 0~4)을 축별 표에 없는 값이라 `ValueError`로 거부한다. 예: `{"axis":"sex","resolution":2}`.

**주의 — 지금의 `not in RESOLUTION[axis]` 검사는 범위 검사도 겸하고 있다.** 그냥 clamp로 바꾸면 5 같은 값도 흡수된다. 범위 검사를 남기고 그 뒤에 clamp한다:

```python
# src/kopl/c2_specificity/engine.py — 93~105행 부근
if isinstance(resolution, bool) or not isinstance(resolution, int):
    raise TypeError(f"conditions[{index}].resolution은 정수여야 합니다.")
if not 0 <= resolution <= 4:                       # 계약 범위 — 그대로 거부
    raise ValueError(f"resolution은 0~4여야 합니다: {resolution!r}")
resolution = min(resolution, max(RESOLUTION[axis]))   # 축 최대 단계로 clamp (sex 2→1, age 4→3)
levels[axis] = max(levels[axis], resolution)
```

테스트: `tests/test_c2_risk.py`는 현재 **10개 케이스**(일반 4 + parametrize 6). sex clamp 기대값을 맞추고, **음수 · 5 · 비정수 거부** 케이스를 추가한다.

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/test_c2_risk.py -v
```

권장 2건(선택): `confidence`가 점수에 곱해지지 않음을 고정하는 테스트 1개 · `risk_by_axis` docstring에 「계약 필드 검증은 호출자 책임」 한 줄.

### 월~화 — `span_to_condition()` 구현

[#261 결정 코멘트 (9/19)](../../issues/261#issuecomment-5737937465) 기준. 파일은 `src/kopl/c2_specificity/clues.py`(신규), 상수는 `model.py`에 모은다.

**출력은 `specificity.schema.json`의 `condition` 전체 필드**여야 한다 — `risk_total`은 `axis`·`resolution`만 보지만, 같은 객체가 W7에 `specificity()`(k 계산)로도 들어간다:

```python
# src/kopl/c2_specificity/clues.py
from __future__ import annotations

# 스팬 type → C2 axis. REL_HOME·REL_WORK 는 축이 아니라 수식자 (아래 build_conditions 에서 처리)
TYPE_TO_AXIS = {
    "LOC_ADMIN": "location", "LOC_FACILITY": "location",
    "AGE": "age", "SEX": "sex", "JOB": "occupation",
    "FAM": "family", "COMMUTE": "commute", "INCOME": "income",
}
LEVEL_CONFIDENCE = {"explicit": 1.0, "implicit": 0.8, "inferential": 0.5}


def span_to_condition(span: dict, post_id: str) -> dict | None:
    """골드 스팬 한 개 → condition 한 개. 조건이 안 되면 None.

    None 인 경우: subject == "other" · REL_HOME/REL_WORK · LOC_ADMIN 미해석 · LOC_FACILITY 코드 없음
    """
    if span["subject"] == "other" or span["type"] not in TYPE_TO_AXIS:
        return None
    axis = TYPE_TO_AXIS[span["type"]]
    conf = LEVEL_CONFIDENCE[span["level"]]
    if span["subject"] == "unknown":
        conf *= 0.5
    resolution, kind, value, geo_code = _resolve(span)   # 아래 표
    if resolution is None:
        return None
    cond = {"axis": axis, "kind": kind, "resolution": resolution,
            "confidence": round(conf, 2), "source_post_ids": [post_id]}
    if geo_code:
        cond["geo_code"] = geo_code
    else:
        cond["value"] = value
    return cond
```

**`_resolve()` — 축별 resolution 표** (첫 열은 입력 `span.type`, 출력 axis는 위 매핑):

| span.type | resolution | kind | value / geo_code |
|---|---|---|---|
| LOC_ADMIN | `engine.resolve(text)` 로 후보 코드 → 사전 `regions[code]["level"]`: `sido`→1 · `sigungu`→2 · `emd`→3. **코드 자릿수로 판별하지 않는다** (사전 코드는 전부 10자리). 후보 0개 → None. 후보 여럿이면 가장 넓은 level | `administrative_area` | `geo_code` |
| LOC_FACILITY | `facilities.py` 해석기가 코드를 주면 4, 없으면 None | `facility` | `geo_code` |
| AGE | 정확 나이(`서른여덟`·`38`) 파싱되면 3, 세대 표현(`30대`·`마흔 넘어`) 1, 파싱 불가 1 | `age_exact` / `age_band` | span.text |
| SEX | 항상 1. **배우자 호칭(`남편`·`아내`)이면 `family` 1 조건을 하나 더 만든다** (label-schema §3-2) | `sex` | span.text |
| JOB | explicit 2 · implicit/inferential 1. **3(직장 특정)은 라벨만으로 금지** | `job_group` | span.text |
| FAM | 학년·자녀 수 정규식(`초3`·`둘째`) 맞으면 3 · explicit/implicit 2 · inferential 1 | `family_status` | span.text |
| COMMUTE | 노선·역 이름 있으면 2, 나머지 1 | `commute_mode` | span.text |
| INCOME | 항상 1 | `income_band` | span.text |
| REL_HOME · REL_WORK | **조건 안 만듦 → None.** `build_conditions()` 에서 수식자로 처리 | — | — |

**`build_conditions(post_ids)` — 글 묶음 → condition 목록.** 스팬을 전부 변환한 뒤 두 가지 후처리:

- **REL_HOME(self)** 가 있는 글의 `location` 조건은 `confidence` 를 1.0으로 올린다
- **REL_WORK** 가 있는 글은 `location` 조건은 그대로 두고 `{"axis":"commute","kind":"commute_mode","value":"REL_WORK","resolution":1,"confidence":0.5}` 를 추가한다

같은 축 조건이 여러 개여도 된다 — `risk_total` 이 축별 max(resolution) 하나만 쓴다 (규칙 1).

**`span_id`는 condition에 넣지 않는다** — `specificity.schema.json`의 condition이 `additionalProperties: false`라 계약 검증에서 깨진다. `contributions[].clue_ids`·`top_spans`는 아래 생성기에서 `clue_index`/`span_index`로 `leave_one_out()`에 넘긴다 (#261 9/20 정정).

**입력은 골드로 한다.** B `infer.py` 출력은 `level=implicit`·`subject=self` 고정값이라 이 분기가 작동하지 않는다 (B 섹션 참고). 골드 파일은 최상위 `gold/*_spans.jsonl`(`reviewed: true` 만) **하나뿐이다.** `gold/blind/`·`gold/detect/`(교사 출력)·`iaa*/`·`stage2/`는 쓰지 않는다.

> ⚠️ **blind 를 합치지 않는다.** blind 200 은 같은 글을 C 가 독립 라벨링한 별도 정본이라 최상위와 `span_id` 가 그대로 겹친다 (실측 `A07_b16_s01`). 합치면 중복으로 생성이 중단된다. — 9/21 이전 문구는 「합친다」로 잘못 적혀 있었다. PM 정정 2026-09-22.

```bash
# 스팬 한 개로 손 검산 — 결과가 표와 맞는지
PYTHONIOENCODING=utf-8 python -c "
from kopl.c2_specificity.clues import span_to_condition
print(span_to_condition({'type':'AGE','level':'explicit','subject':'self','text':'서른여덟'}, 'A01_b03'))
# → {'axis':'age','kind':'age_exact','resolution':3,'confidence':1.0,'source_post_ids':['A01_b03'],'value':'서른여덟'}
"
```

### 화~수 — `gen_contribution_targets.py` + PR

`loo.py`의 `risk_fn`(정렬된 post_id 튜플 → 0~100)에 `risk_total`을 붙인다. `leave_one_out()`이 이미 `contribution.schema.json` 형식을 그대로 반환하므로 어댑터는 `risk_fn` 하나다.

```python
# scripts/gen_contribution_targets.py
"""인물별 LOO 기여도 = D 2단 학습의 증류 타깃.

  python scripts/gen_contribution_targets.py \
    --gold     data/corpus/v0/gold \
    --personas data/corpus/v0/personas \
    --out      data/corpus/v0/gold/contribution \
    --exclude-posts data/corpus/v0/splits/test.jsonl
"""
import hashlib, json
from pathlib import Path
from kopl.c2_specificity import risk_total
from kopl.c2_specificity.clues import span_to_condition   # + build_conditions
from kopl.c3_contribution.loo import leave_one_out


def user_ref_for(persona_id: str) -> str:
    # scripts/seed_sns.py 와 같은 규칙 — SNS 의 user_ref 와 반드시 일치해야 E 가 조인할 수 있다
    return "u_" + hashlib.sha256(persona_id.encode("utf-8")).hexdigest()[:12]


def load_spans(gold: Path, persona_id: str, exclude: set[str]) -> dict[str, list[dict]]:
    """post_id → 스팬 목록. 최상위 reviewed 만. 첫 줄은 헤더.

    blind/ 는 합치지 않는다 — 같은 글의 독립 라벨이라 span_id 가 겹친다.
    exclude 는 test split 의 post_id 집합 (아래 ⚠️ 참고).
    """
    by_post: dict[str, list[dict]] = {}
    f = gold / f"{persona_id}_spans.jsonl"
    if not f.exists():
        return by_post
    for line in f.read_text(encoding="utf-8").splitlines()[1:]:
        rec = json.loads(line)
        if "reviewed" in rec and not rec["reviewed"]:
            continue
        if rec["post_id"] in exclude:
            continue
        by_post.setdefault(rec["post_id"], []).extend(rec.get("spans", []))
    return by_post


def main(gold: Path, personas: Path, out: Path, exclude_file: Path | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    exclude = {json.loads(l)["post_id"]                # splits/test.jsonl — D 와 글 집합을 맞춘다
               for l in exclude_file.read_text(encoding="utf-8").splitlines()
               if l.strip()} if exclude_file else set()
    for pfile in sorted(personas.glob("*.json")):
        pid = pfile.stem
        spans = load_spans(gold, pid, exclude)
        if not spans:
            continue                                   # 골드 없는 인물은 건너뛴다 (건너뛴 목록은 PR 에 적는다)

        def risk_fn(post_ids: tuple[str, ...]) -> float:
            conds = build_conditions({p: spans[p] for p in post_ids})
            return risk_total(conds)                   # conds 가 비면 0.0 — 전부-제거 케이스

        # contribution 계약의 clue_ids · top_spans 는 condition 이 아니라 여기서 채운다
        clue_index = {p: [s["span_id"] for s in ss] for p, ss in spans.items()}
        span_index = {p: [{"span_id": s["span_id"], "text_id": s["text_id"]} for s in ss]
                      for p, ss in spans.items()}            # loo.py 가 앞 3개만 쓴다
        result = leave_one_out(user_ref=user_ref_for(pid), post_ids=sorted(spans),
                               risk_fn=risk_fn, clue_index=clue_index, span_index=span_index)
        (out / f"{pid}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
```

실행 → 계약 검증 → 검산:

```bash
python scripts/gen_contribution_targets.py --gold data/corpus/v0/gold \
  --personas data/corpus/v0/personas --out data/corpus/v0/gold/contribution \
  --exclude-posts data/corpus/v0/splits/test.jsonl

# 계약 (전 파일)
for f in data/corpus/v0/gold/contribution/*.json; do
  check-jsonschema --schemafile docs/contracts/contribution.schema.json "$f" || echo "FAIL $f"
done

# 검산표 — PR 본문에 20명 붙인다: persona.ground_truth 대비 축별 max(resolution) 이 말이 되는지
PYTHONIOENCODING=utf-8 python -c "
import json, glob
for f in sorted(glob.glob('data/corpus/v0/gold/contribution/*.json'))[:20]:
    r = json.load(open(f, encoding='utf-8')); pid = f.split('/')[-1][:-5]
    gt = json.load(open(f'data/corpus/v0/personas/{pid}.json', encoding='utf-8'))['ground_truth']
    top = r['output']['contributions'][0]
    print(pid, 'baseline', r['output']['baseline_risk'], 'top', top['post_id'], top['delta'], '| GT', gt['location'], gt['age'], gt['occupation'])
"
```

**검산에서 볼 것 3가지**: ① `baseline_risk` 가 인물 간에 갈리는가 (전부 같은 값이면 변환기가 resolution 을 못 만드는 것) ② rank 1 글이 실제로 지명·나이 단서가 든 글인가 ③ `greedy_path` 가 2~3개 안에서 `residual_risk`(=0) 근처로 내려가는가. 셋 중 하나라도 이상하면 PR 본문에 그대로 적는다 — 고치는 건 W7 튜닝 몫이다.

> ⚠️ **test split(#244) 글은 뺀다** — `--exclude-posts data/corpus/v0/splits/test.jsonl`. 증류 타깃은 **모델이 입력으로 보는 글 집합에 대한 LOO** 여야 한다. D 의 `make_sft_v1.py` 는 test 글을 빼고 학습 예시를 만들기 때문에, 타깃에 test 글이 섞이면 글 집합이 달라 `recommendation` 이 통째로 버려진다 (실측 조인 28/77 → 제외 후 77/77). — 9/21 이전 문구는 「test 글도 생성한다, 빼는 건 D 가」로 반대로 적혀 있었다. PM 정정 2026-09-22.

### 만들 것

```
src/kopl/c2_specificity/clues.py               span_to_condition() · build_conditions() · TYPE_TO_AXIS
src/kopl/c2_specificity/model.py                LEVEL_CONFIDENCE 등 상수 추가 (PR #268 파일)
src/kopl/c2_specificity/test_clues.py           축별 표 케이스 (최소 축마다 1개 + REL 2개 + other/unknown)
scripts/gen_contribution_targets.py             전 인물 실행 스크립트
data/corpus/v0/gold/contribution/<pid>.json     증류 타깃 세트 (커밋한다 — D 학습 입력)
```

### 완료 기준

- [x] `loo.py` LOO 기여도 — 단위 테스트 통과 (#251 머지 · 9/16 · CI guard pass)
- [x] PR #268 — 범위 검사 유지 + clamp · 거부 케이스 3개 추가 · 재제출 → 머지 (9/22)
- [ ] `span_to_condition()` + `build_conditions()` — 표 그대로 · `test_clues.py` 통과 · condition 전체 필드 (화)
- [ ] `gen_contribution_targets.py` — test split 제외 후 생성(`--exclude-posts`) · 건너뛴 인물 목록을 PR 본문에 기재 · `check-jsonschema` 전 파일 통과 (수) — 생성기 수정은 [#269](../../pull/269)
- [ ] PR — 검산표 20명 + 건너뛴 인물 목록 + 검산 3가지 소견 (수 9/23 · 늦으면 월 9/28)

---

## D · 박재현 — PM 역할

> 전체 매뉴얼 [docs/roles/D-stage2.md](docs/roles/D-stage2.md)

### 현황

QLoRA 3ep adapter v1 확정 (verdict 90% · dev_loss 0.0044 · #264 · 9/18). 추가 학습 불필요. W6는 PM 역할 집중.

### 월 9/21 11:15 — KISIA 줌 주간보고회 발표

W5 성과 발표. [위 팀 회의 §0](#0-전원-공통--월-921-1115-kisia-줌-주간보고회) 표 참고.

### 수 9/23 23:59 — 주간보고서 취합

팀원 5명 보고 수합 + KISIA 제출.

### 목 9/24 21:00 — 멘토링 (연휴 첫날 · 진행 여부 확인)

정례 목요일이 연휴 첫날이다. 9/17 멘토링에서 「추석 고려해 조율」하기로 했으므로 **월요일에 멘토님께 날짜를 확인**하고 확정되면 여기 갱신한다.

**안건 (정해지면):**
1. W6 진행 공유 — C 증류 타깃 진행 상황
2. E 활동 메타 마무리 보고
3. W7 대응 — B 1단 F1 확정·C 기여도 v1 확정·D Qwen3 v1 확정

### w05 태그 — 완료 (9/22)

`w05` → `c792573` (PR #268 머지 커밋). 원격 태그는 `w01 w02 w04 w05`. compare 링크는 주간활동보고서 「활동 내용」에 넣는다:

https://github.com/jaepaly/KISIA_Project/compare/w04...w05

다음 주부터는 `bash scripts/tag_week.sh w06` 한 줄이면 된다 (태그 + push + compare 링크 출력).

### PM 몫

| 언제 | 무엇 |
|---|---|
| 일 9/20 저녁 | 팀원 보고 5줄 취합 (KISIA 줌 전날) |
| **월 9/21 11:15** | KISIA 줌 주간보고회 발표 |
| 월 9/21 | 멘토님께 멘토링 날짜 확인 (목 9/24 = 연휴) |
| **수 9/23 23:59** | 주간보고서 최종 제출 |
| 9/22 | w05 태그 — **완료** (`c792573`) |

### 완료 기준

- [ ] 월 9/21 KISIA 줌 발표 완료
- [ ] 멘토링 날짜 확정 · README 갱신
- [ ] 주간보고서 수 9/23 23:59 제출
- [x] w05 태그 — 9/22 `c792573` · [compare](../../compare/w04...w05)

---

## E · 이지희 — 활동 메타 필드

> 전체 매뉴얼 [docs/roles/E-system.md](docs/roles/E-system.md) · [howto/e-integration.md](docs/roles/howto/e-integration.md)

### ⭐ 이번 주 E 의 핵심 — 활동 메타의 **남은 조각**을 채운다

활동 메타 3종(닉네임·위치태그·작성시각)과 공개/비공개는 조치 ②③ 시연의 재료다 ([roadmap §4](docs/roadmap.md) · 선행 PoC에서 활동 메타 관리가 위험도 감소 1위). **골격은 W3에 이미 다 들어가 있다** — 이번 주는 비어 있는 것만 채운다.

```
W3: 스키마·토글·표시 ✅ → W5: 3화면 연결 ✅ → W6: 시딩 위치태그 · 시간대 분포 · 작성 시 공개범위
                                              → W7: exp8 축약판 · 중간점검 초안 → W9: 에디터 실시간 경고 (D와)
```

**이미 돼 있는 것 — 다시 만들지 않는다:**

| 항목 | 어디에 |
|---|---|
| `geo_tag` · `visibility` · `created_at` 컬럼 | `apps/sns/schema.sql` 25~27행 |
| 글별 공개/비공개 전환 | `app.py:127` `POST /posts/<id>/visibility` · `post.html:26` · `profile.html:27` 버튼 |
| 비공개 글은 `/api/export` 에서 제외 | `app.py:181~189` |
| 작성 화면 위치태그·작성시각 입력 | `templates/new.html` 28~38행 |
| 닉네임·위치태그·작성시각 표시 | `post.html:10~12` · `profile.html:24~25` |

**비어 있는 것 3가지** ([howto/e-sns.md §6](docs/roles/howto/e-sns.md)):

1. 시딩 글의 `geo_tag` 가 **전부 NULL** (`scripts/seed_sns.py:163` 이 `None` 을 넣는다) → 조치 화면에서 「이 태그를 지우면 −n」을 보여줄 재료가 없다
2. 프로필에 **시간대 분포 막대** 없음 — 글마다 시각만 찍힌다. 새벽에 몰린 막대가 시연에서 가장 잘 먹힌다
3. 작성 화면에 **최초 공개범위 선택** 없음 — `app.py:113` 이 `'public'` 고정 (전환은 게시 후에만 가능)

### 월 — 시딩 `geo_tag` 채우기

인물 `ground_truth.location` 은 `"서울특별시 마포구 망원동"` 꼴이다. 위치태그는 **시군구 수준까지만** 넣는다 — 스키마 예시(`'용인시 기흥구'`)와 맞추고, 읍면동은 본문 단서와 결합했을 때만 좁혀지게 남겨둔다.

```python
# scripts/seed_sns.py — seed_persona() 안, iter_posts 루프 위에 추가
def geo_tag_for(persona: dict) -> str | None:
    loc = (persona.get("ground_truth") or {}).get("location") or ""
    parts = loc.split()
    return " ".join(parts[1:-1]) if len(parts) >= 3 else (loc or None)   # "서울특별시 마포구 망원동" → "마포구"

# 루프 안 — 인물별 seed 고정 rng 로 글의 30% 에만 태그 (전부 달면 시연에서 「지우기」가 재미없다)
tag = geo_tag_for(persona)
geo_tag = tag if (tag and not record.get("negative_control") and rng.random() < 0.30) else None
# INSERT 의 마지막 인자 None → geo_tag
```

`INSERT OR IGNORE` 라 **이미 시딩된 DB는 안 바뀐다.** `--reset` 으로 다시 넣는다:

```bash
python scripts/seed_sns.py --corpus data/corpus/v0/posts --personas data/corpus/v0/personas \
  --db data/interim/sns.db --reset
sqlite3 data/interim/sns.db "SELECT COUNT(*), COUNT(geo_tag) FROM posts WHERE source='seed';"
# 두 번째 숫자가 첫 번째의 10~12% 면 정상 — 잡담(negative_control, 코퍼스의 64%)엔 안 달고 나머지의 30% 에만 달기 때문.
# 잡담 제외 기준으로는 25~35%. (9/22 정정 — 종전 「전체의 25~35%」는 NC 를 설계값 10~15% 로 가정한 오기. #271 참고)
```

### 화 — 프로필 시간대 분포 막대

`e-sns.md §5` 검증 SQL 3번을 그대로 화면에 올린다. 라우트에서 24칸 집계를 넘기고, 템플릿은 CSS 막대만 — JS 없음.

```python
# apps/sns/app.py — profile() 안, posts 조회 다음에
rows = db().execute(
    "SELECT CAST(substr(created_at,12,2) AS INTEGER) AS h, COUNT(*) AS n"
    " FROM posts WHERE author_id = ? GROUP BY h", (a["author_id"],)).fetchall()
hours = [0] * 24
for r in rows:
    hours[r["h"]] = r["n"]
peak = max(hours) or 1
return render_template("profile.html", a=a, posts=posts, hours=hours, peak=peak)
```

```html
<!-- apps/sns/templates/profile.html — 「글 n편 · 가입」 줄 아래 -->
<p class="post-meta" style="margin-top:12px;">시간대별 글 수</p>
<div style="display:flex;align-items:flex-end;gap:2px;height:60px;">
  {% for n in hours %}
    <div title="{{ loop.index0 }}시 {{ n }}편"
         style="flex:1;background:{% if loop.index0 < 6 %}#c0392b{% else %}#7f8c8d{% endif %};
                height:{{ (n * 100 / peak)|int }}%;min-height:1px;"></div>
  {% endfor %}
</div>
<div style="display:flex;font-size:11px;color:#888;"><span style="flex:1">0시</span><span style="flex:1">6시</span><span style="flex:1">12시</span><span style="flex:1">18시</span></div>
```

새벽(0~5시)만 색을 다르게 둔 이유: 시연에서 「이 사람은 새벽에 쓴다」가 한눈에 보여야 한다. `typical_active_hours` 가 「평일 밤 10시 이후」인 인물(A01)의 프로필을 열어 22~23시 막대가 솟는지 확인.

### 수 — 작성 시 공개범위 선택 + 회귀 확인

```html
<!-- apps/sns/templates/new.html — created_at 입력 아래 -->
<label for="visibility">공개 범위</label>
<select name="visibility" id="visibility">
  <option value="public">공개</option>
  <option value="private">비공개</option>
</select>
```

```python
# apps/sns/app.py — create_post()
visibility = f.get("visibility", "public")
if visibility not in ("public", "private"):
    abort(400)
# INSERT 의 'public' 리터럴을 ? 로 바꾸고 visibility 를 인자에 추가
```

회귀 확인 — 비공개 글이 export 에서 빠지는 것은 W3 기능이지만, INSERT 를 건드렸으니 다시 돌린다:

```bash
python -m pytest apps/sns/test_export.py -v          # 기존 테스트 + 「private 로 만든 글은 export 에 없다」 케이스 1개 추가
sqlite3 data/interim/sns.db < scripts/check_seed.sql  # 빈 시각 0건 · 시간대 2개 이상
```

### 만들 것

```
scripts/seed_sns.py                    geo_tag_for() · 30% 태그 · --reset 재시딩
apps/sns/app.py                        profile(): hours/peak · create_post(): visibility
apps/sns/templates/profile.html        시간대 분포 막대
apps/sns/templates/new.html            공개 범위 select
apps/sns/test_export.py                private 제외 케이스 1개
```

### 완료 기준 (e-sns.md §9 W6)

- [x] 닉네임·위치태그·작성시각이 본문/프로필에 보인다 (W3)
- [ ] 잡담 제외 시딩 글의 25~35% (전체 기준 10~12%) 에 시군구 수준 `geo_tag` 가 들어 있다 (`--reset` 후 SQL 로 확인)
- [ ] 프로필에 시간대 분포 막대가 보인다 — A01 프로필에서 22~23시가 솟는다
- [ ] 작성 화면에서 비공개로 올린 글이 `/api/export` 에 없다 (`test_export.py` 통과)

---

## 이번 주 일정

| 요일 | 시각 | 누가 | 무엇 |
|---|---|---|---|
| **월 9/21** | 11:15 | D(PM) | KISIA 줌 주간보고회 발표 |
| 월 | | D(PM) | 멘토님께 멘토링 날짜 확인 (목 9/24 = 연휴 첫날) |
| 월 | | C | PR #268 — 범위 검사 유지 + clamp · 거부 케이스 추가 · 재제출 |
| 월 | | E | `seed_sns.py` geo_tag 30% · `--reset` 재시딩 |
| 월~화 | | C | `clues.py` span_to_condition() · build_conditions() · test_clues.py |
| 월~화 | | B | E에게 체크포인트·`--min-span-score`·level/subject 제한 이슈 코멘트 |
| 화 | | E | 프로필 시간대 분포 막대 |
| 화~수 | | C | `gen_contribution_targets.py` · 전 인물 · 계약 검증 · 검산표 20명 · PR |
| 수 | | E | 작성 시 공개범위 select · test_export 케이스 |
| 수 | | A | decisions.md W5 결정 3건 (비동기 · 연휴 뒤여도 됨) |
| **수 9/23 23:59** | | 팀원 5명 | 주간보고서 5줄 PM에게 |
| **목 9/24 ~ 일 9/27** | | 전원 | **추석 연휴 — 작업 없음** (멘토링은 날짜 확정 후 여기 갱신) |
| C PR 머지 후 | | D | w05 태그 (+ w04 push) · 연휴 걸치면 월 9/28 |

---

## 이번 주 반드시 지킬 것

**① C는 span_to_condition()에서 REL 축을 조건으로 만들지 않는다.**
REL_HOME·REL_WORK는 수식자다. REL_HOME(self)는 동글의 location confidence를 1.0으로 올리고, REL_WORK는 location 그대로 + commute 1(conf 0.5)만 추가한다.

**② E는 `apps/sns/` 골격을 다시 만들지 않는다.**
스키마·토글·표시는 W3에 끝났다. 이번 주는 시딩 `geo_tag`·시간대 막대·작성 시 공개범위 세 조각만. `data/interim/sns.db`는 커밋하지 않는다 (`--reset`으로 언제든 재생성).

**③ D는 w05 태그를 C PR 머지 전에 달지 않는다.**
증류 타깃 세트가 포함된 커밋이 main에 들어온 뒤에 태그를 단다.

---

## 막히면

| 상황 | 어떻게 |
|---|---|
| LOC_ADMIN 코드가 시도인지 읍면동인지 모르겠다 | `engine.resolve(text)` 는 코드 **목록**을 준다. 계층은 사전 `regions[code]["level"]` (`sido`·`sigungu`·`emd`) 로 본다 — **자릿수로 판별하지 않는다**, 사전 코드는 전부 10자리 |
| 지명 후보가 여러 개 나온다 (동명이인) | 가장 넓은 level 을 쓴다 (좁게 잡으면 위험도 과대). 애매하면 `resolve_info()` 결과를 PR 에 적고 W7 튜닝으로 |
| 조건 계약 검증에서 `value` 또는 `geo_code` 필수라고 나온다 | `specificity.schema.json` condition 은 `anyOf[value, geo_code]`. LOC 축은 `geo_code`, 나머지는 `value`(스팬 텍스트) |
| PR #268 테스트 cp949 오류 | `PYTHONIOENCODING=utf-8 python -m pytest` |
| clamp 수정 후 기존 테스트 기댓값 불일치 | sex `resolution=2` 가 이제 거부 대신 1 로 clamp 된다. `test_c2_risk.py` 의 거부 기대 케이스를 clamp 기대로 바꾸고, 5·음수·비정수 거부 케이스를 새로 넣는다 |
| `--reset` 했는데 geo_tag 가 여전히 NULL | `seed_persona()` 의 INSERT 마지막 인자가 아직 `None` 인지 확인 (`scripts/seed_sns.py:163`) |
| 시간대 막대가 전부 같은 높이 | `scatter_created_at()` 이 안 돈 것 — `check_seed.sql` 3번 쿼리로 시간대가 2개 이상 갈리는지 확인 |
| `check-jsonschema` 명령이 없다 | `pip install check-jsonschema` |
| SNS 서버 포트 3000 이 안 켜진다 | [howto/e-sns.md §1·§8](docs/roles/howto/e-sns.md) 확인 또는 E에게 |
| PR 머지가 안 된다 | 리뷰어에게 요청 — 재촉하지 말고 한 번만 |

---

## 저장소 구조

```
KISIA_Project/
├─ README.md                      ← 이번 주 할 일 (이 문서)
├─ CONTRIBUTING.md                브랜치·커밋·리뷰 규칙
├─ docs/
│  ├─ overview.md                 프로젝트가 뭔지
│  ├─ plan.md                     계획 전문 (v2.2)
│  ├─ roadmap.md                  12주 주차별 계획
│  ├─ roles/                      역할별 작업 매뉴얼 5종
│  ├─ contracts/                  ⭐ 모듈 인터페이스 계약 6종 (W2 고정)
│  ├─ design/                     설계서 (W4 제출 완료)
│  ├─ decisions.md                결정 기록 [DEC-NNN]
│  ├─ mentor-log.md               멘토 피드백 [MF-NNN]
│  └─ RULES-DO-NOT.md             절대 하면 안 되는 것
├─ src/kopl/
│  ├─ c1_span/                    1단 탐지 (B)
│  ├─ c2_specificity/             특정성 엔진 (C) · clues.py (W6 신규)
│  ├─ c3_contribution/            기여도 엔진 (C · W5 신규)
│  ├─ c4_stage2/                  2단 추론·가명화 (D · W5 신규)
│  └─ c5_corpus/                  코퍼스 생성·교사 라벨 (D · A)
├─ data/
│  ├─ corpus/v0/personas/         인물 JSON (115명 · W4 동결)
│  ├─ corpus/v0/posts/            생성 글 (3,092편 · W4 동결)
│  ├─ corpus/v0/gold/             골드셋 검수분 (417편 587스팬)
│  ├─ corpus/v0/gold/blind/       blind 분 ✅ (C · #229 머지 완료 9/14 · 159편 267스팬)
│  ├─ corpus/v0/gold/iaa/         IAA 배정 + A·C 라벨링
│  ├─ corpus/v0/gold/contribution/ 증류 타깃 세트 (C · W5 신규)
│  ├─ corpus/v0/splits/           train/test 분리 (A · W5 신규)
│  ├─ realism/cards/              리얼리즘 카드 18장
│  └─ dict/admin/                 행정구역·인구 사전
├─ experiments/
│  ├─ exp01-baseline/             베이스라인 3종 + LLM 상한 (W4 완성)
│  ├─ exp05-model-size/           Qwen3 크기 비교 (W3 완료)
│  ├─ exp06-finetune/             1단 파인튜닝 (B · W4~)
│  └─ exp07-qwen3-finetune/       2단 QLoRA (D · W4~)
├─ apps/
│  ├─ sns/                        가상 SNS (v0 + 시딩 완료)
│  └─ analyzer/                   분석 웹앱 (E · W5 신규)
├─ models/
│  └─ registry.md                 모델 체크포인트 등록부
└─ scripts/                       운영 스크립트
```

---

## 현재 미결 (9/22 기준)

**PR**
- [x] PR #268 C `risk_total` + clamp 수정 — 머지 (9/22)
- [ ] [#269](../../pull/269) 증류 타깃 생성기 수정 (blind 합침 제거 · test 제외) — **C 리뷰 대기** · base `C/c2/span-to-condition` → 그 PR 을 C 가 먼저 연다

**이슈 — W6**
- [ ] #261 span_to_condition() 구현 → C3 어댑터 → 증류 타깃 PR
- [x] w05 태그 (9/22)

**장기**
- [ ] [#206](../../issues/206) #201 후속 추적 — 각자 인물 JSON 확인
- [ ] [MF-015](docs/mentor-log.md) 대회 제출 요건·배포 범위 확인
- [ ] 잡담 글 「단서 0」 계약 vs 자영업·농업 인물의 삶 (#201 남은 쟁점) — v2
