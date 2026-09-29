# exp-010: [필수] 조치 3단계 재현 — 위험도 감소 −54~61%

## 무엇을 왜 재는가

PoC 결과 「비공개·위치태그 제거·리라이트 세 단계를 거치면 위험도가 −54~61% 감소한다」를 코퍼스 v0
표본으로 재현한다 ([D-stage2.md](../../docs/roles/D-stage2.md) §1 ④). 실제 엔진(C2 위험도 · C3 LOO)과
골드 스팬을 써서 수치 근거를 확인하고, 입출력을 C 에 넘겨 수요일 공동 검산에 쓴다.

## 정의

| 항목 | 정의 |
|---|---|
| **본 표본** | exp09(#278)와 같은 **239편 · 105명** (1단 test − 옛 IAA 16편) · body/title/photo_caption 스팬 전부 |
| **참고 표본** | 같은 105명의 **전체 글** (최상위 골드 · 검수 10~30%, C 계열 18명 제외 → 87명) |
| **위험도** | C2 `risk_total` — 7축 각 최고 해상도의 평균 · condition = 골드 스팬 + 위치태그 condition |
| **조치 순서** | 1) 비공개 → 2) 활동 메타(위치태그 제거) → 3) 리라이트 |
| **비공개 편수 k** | LOO greedy 앞 k편 · k = min(max(1, round(n×3/19)), n−1) — PoC R1 19편 중 3편 비공개 근거 |
| **위치태그** | `scripts/seed_sns.py` 임시 DB 실행 결과 (전체 코퍼스 · seed 42 · 잡담 제외 30%) |
| **리라이트 모드 3가지** | explicit(명시 단서만 제거 — **본 지표**) · weaken(해상도 한 단계) · remove(전부 제거 — 상한) |
| **리라이트 구현** | 교사 리라이트 라벨 0건이라 규칙으로 모사 (2단 리라이터는 W9 예정) · 모델 호출 없음 |

> **본 지표는 explicit(명시 단서만 교체)** — 암묵·추론 단서는 문맥이라 남는다. PM 결정 2026-09-29.

## 설정

| 항목 | 값 |
|---|---|
| 측정일 | 2026-09-29 |
| 코퍼스 버전 | v0 · test split #244 · test.jsonl SHA-256 `9662a167…` (exp09 manifest 일치) |
| 엔진 | C2 risk_total · C3 leave_one_out (src/) |
| 검증 | 계약 condition 스키마 대조 747개 (표본) · 4859개 (전체 이력) — 위반 0 |

## 결과 (2026-09-29)

### 본 표본 (239편 · 99명 유효)

> 기준선 0인 인물 6명(단서 없는 noise only) 제외.

| 단계 | 기준선 | 비공개 후 | 위치태그 후 | 리라이트 후 |
|---|---|---|---|---|
| **평균 위험도** | 17.73 | 10.12 | 8.22 | 6.69 |

| 리라이트 모드 | 평균 감소 | **중앙값** | pooled |
|---|---|---|---|
| **explicit (명시만)** — **본 지표** | −58.8% | **−58.6%** | −62.3% |
| weaken (한 단계 약화) | −89.8% | −100% | −90.4% |
| remove (전부 삭제) | −100% | −100% | −100% |

**PoC 범위(−54~61%) 대비 분포 (explicit):**
- 61% 초과: 49명 / 범위 내: 13명 / 54% 미달: 37명 (평균 58.8% — 범위 중앙에 위치)

### 단독 기여 (explicit 모드)

| 단계 | 단독 평균 감소 | 단독 중앙값 |
|---|---|---|
| 비공개 | −40.0% | −42.9% |
| 위치태그 제거 | −18.4% | 0% |
| 리라이트(explicit) | −15.7% | 0% |

### 참고 표본 (전체 이력 · 87명)

| 리라이트 모드 | 평균 감소 | 중앙값 |
|---|---|---|
| explicit | −66.6% | −67.1% |
| weaken | −93.8% | −100% |
| remove | −100% | −100% |

## PoC 재현 여부

| PoC 주장 | 재현 여부 | 비고 |
|---|---|---|
| 3단계 합계 −54~61% | **재현** — mean −58.8%, median −58.6% | 표본 인물당 2.3편으로 비공개 단계가 과장될 수 있음 |
| 「위치태그 관리가 1위」 | **재현 안 됨** | 단독: 비공개 −40% > 위치태그 −18% > 리라이트 −16% |

「위치태그 관리가 1위」가 재현되지 않는 이유:

- PoC 에서 위치태그 기여가 컸던 것은 **닉네임·활동 시간대**가 같이 포함됐기 때문으로 추정 — 이 재현에서 시간대는 측정 축이 없고, 닉네임은 C2 위험도 축이 없다
- 구 단위 위치태그와 본문 location 단서가 겹쳐 단독 기여가 중복 계산되지 않는다

## 한계

1. **표본이 작다.** 인물당 2.3편(중앙 2편)이라 비공개 단계(k ≥ 1)가 위험도를 실제보다 많이 낮출 수 있다. 전체 이력(87명 · 인물당 평균 27편) 숫자가 더 현실적이다.
2. **교사 리라이트 라벨이 없다.** explicit 모드는 명시 단서의 condition 을 제거하는 규칙이고, 실제 문장 재작성은 아니다. 2단 리라이터(W9)로 측정하면 달라진다.
3. **라벨 출처가 섞여 있다.** 표본 골드는 C-검수(blind) 159편 + 교사 보조 검수(noise) 80편. 전체 이력 골드는 검수 10~30%, C 계열 18명은 최상위 골드 없어 제외.
4. **위치태그는 seed_sns 로 모사한 것이다.** 실제 SNS 에서 사용자가 붙이는 태그와 분포가 다를 수 있다.

## 확인 방법

```bash
export PYTHONIOENCODING=utf-8
python experiments/exp10-action-repro/build_inputs.py    # inputs_sample.jsonl · inputs_full.jsonl · results/preview.json
```

`data/*.jsonl` 은 커밋하지 않는다 (재생성 가능 · `.gitignore`). `results/preview.json` 만 추적한다.

## C 공동 검산용 입력 형식 (`inputs_sample.jsonl` 1행 구조)

```jsonc
{
  "persona_id": "…",
  "user_ref": "u_xxxxxxxx",       // 8자리 (exp09 와 같은 형식)
  "post_ids": ["pid1", …],
  "posts": [{ "post_id": "…", "kind": "clue|noise",
    "label_source": "blind|reviewed", "negative_control": false, "geo_tag": "강남구" }],
  "baseline": {
    "risk": 17.5, "by_axis": {"age": 0.0, …}, "conditions": [/* condition 배열 */]
  },
  "actions": [
    { "step": 1, "action_type": "unpublish", "post_ids": ["…"], "k_max": 1, "stalled": false,
      "loo_contributions": [{"post_id": "…", "delta": 0.0, "rank": 1}],
      "greedy_path": [{"remove": "…", "risk_before": 0.0, "risk_after": 0.0, "delta": 0.0}] },
    { "step": 2, "action_type": "activity_meta", "meta_field": "geo_tag",
      "remove_conditions": [/* 위치태그 condition */] },
    { "step": 3, "action_type": "rewrite",
      "modes": { "explicit": {"spans": [{"post_id": "…", "span_id": "…", "text_id": "body",
        "type": "AGE", "level": "explicit", "before": [/*condition*/], "after": []}]},
        "weaken": {"spans": […]}, "remove": {"spans": […]} } }
  ],
  "preview": {
    "cumulative": { "baseline": 17.5, "after_unpublish": 10.0, "after_meta": 8.0,
      "after_rewrite": {"explicit": 6.5, "weaken": 1.5, "remove": 0.0} },
    "solo": { "unpublish": 10.0, "activity_meta": 14.0,
      "rewrite": {"explicit": 14.5, "weaken": 5.0, "remove": 0.0} }
  }
}
```
