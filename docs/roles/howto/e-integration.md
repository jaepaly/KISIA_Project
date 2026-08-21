# 통합 — 남의 산출물을 기다리지 않는 법 (E 실무)

> **W5의 목표는 "스캔이 한 번 끝까지 돌아가는 것"이다. 숫자가 맞는 것은 목표가 아니다.**
> 배경은 [E-system.md §6](../E-system.md).

---

## 0. 왜 기다리면 안 되나

통합을 마지막에 붙이면 **터졌을 때 고칠 시간이 없다.** 그래서 원래 W8이던 통합을 W5로 앞당겼다([roadmap.md §1](../../roadmap.md)). 그런데 W5에는 B의 모델도, C의 엔진도, D의 2단도 아직 완성이 아니다.

**그래서 가짜로 먼저 붙인다.**

> **계약이 있으면 상대의 코드가 없어도 그 자리에 가짜를 놓을 수 있다.**
> 계약을 목요일에 고정하는 진짜 이유가 이것이다. 계약은 문서가 아니라 **빈자리의 모양**이다.

---

## 1. 원리 — 자리를 먼저 만든다

```
[SNS 3000] ──export JSON──▶ [분석기 8000]
                              ├─ engines/c1_span      ← mock 또는 real
                              ├─ engines/c2_specificity
                              ├─ engines/c3_contribution
                              └─ engines/c4_stage2
```

분석기는 **네 개의 함수를 부를 뿐**이고, 그 함수가 진짜인지 가짜인지 모른다. 스위치는 환경변수 하나.

```bash
ENGINE_MODE=mock   # 기본값. 아무것도 없어도 3화면이 돈다
ENGINE_MODE=real   # 실제 모델
```

---

## 2. 목(mock) 엔진 만들기

**목의 유일한 요구조건: 계약 스키마를 통과할 것.** 숫자는 아무래도 좋다.

```python
# apps/analyzer/engines/mock.py
"""실제 모델이 오기 전까지 쓰는 가짜 엔진.
   숫자는 의미 없다. 형식만 계약과 같으면 된다."""

_KEYWORDS = [("저수지","LOC_FACILITY"), ("호수","LOC_FACILITY"), ("역","LOC_FACILITY"),
             ("퇴근","COMMUTE"), ("출근","COMMUTE"),
             ("첫째","FAMILY"), ("아이","FAMILY")]

def detect_spans(post: dict) -> dict:          # B(c1) 자리
    spans = []
    for kw, typ in _KEYWORDS:
        i = post["body"].find(kw)
        if i >= 0:
            spans.append({"start": i, "end": i + len(kw), "text": kw,
                          "type": typ, "level": "inferential", "score": 0.5})
    return {"schema_version": "1.0", "post_id": post["post_id"], "spans": spans}

def specificity(attributes: dict) -> dict:      # C(c2) 자리
    k = 12345 if attributes.get("region_code") else None
    return {"schema_version": "1.0",
            "query": {"attributes": attributes},
            "result": {"k": k,
                       "level": "ACCEPTABLE" if k and k >= 5 else "UNKNOWN",
                       "basis": {"source": "MOCK", "as_of": "1970-01"}}}

def contribution(author_id: str, posts: list) -> dict:   # C(c3) 자리
    # 글이 많을수록 위험도가 올라가는 형태만 흉내낸다
    base = min(20 + 4.0 * len(posts), 95.0)
    items = [{"post_id": p["post_id"], "delta": -round(base / max(len(posts), 1), 1),
              "rank": i + 1, "top_spans": ["MOCK 근거"]}
             for i, p in enumerate(posts)]
    return {"schema_version": "1.0", "author_id": author_id,
            "baseline_risk": round(base, 1), "posts": items}

def stage2(payload: dict) -> dict:              # D(c4) 자리
    return {"schema_version": "1.0", "input": payload, "output": {
        "findings": [
            {"attr": "residence", "abstained": False,
             "verdict": "동 단위로 특정 가능", "evidence_post_ids": [], "confidence": 0.5},
            {"attr": "income", "abstained": True, "verdict": None,
             "evidence_post_ids": [], "confidence": 0.1},
        ],
        "recommendation": {"target_risk": 40.0, "expected_risk_after": 41.0,
                           "actions": [{"type": "private", "post_ids": []}]}}}
```

### ⭐ 목 출력도 계약 검사를 통과시킨다

```bash
python -c "from apps.analyzer.engines import mock, json; \
  json.dump(mock.stage2({'author_id':'S01','posts':[]}), open('/tmp/o.json','w'))"

check-jsonschema --schemafile docs/contracts/stage2-io.schema.json /tmp/o.json
```

**여기서 통과하면 실제 모델이 왔을 때 붙는 것이 보장된다.** 목이 계약을 어기면 목의 형식에 맞춰 화면을 만들게 되고, 실제 모델이 오는 날 화면을 다시 짜게 된다.

> 그래서 목을 만드는 순서는 **화면 → 목**이 아니라 **계약 → 목 → 화면**이다.

### 목 하나를 일부러 기권시켜 둔다

위 `stage2` 목에서 `income`을 `abstained: true`로 둔 이유가 있다. **화면이 기권을 표시할 수 있는지 지금 확인해야** 하기 때문이다. 목이 전부 성공만 주면 실제 모델이 기권했을 때 화면이 빈칸으로 뜬다.

같은 이유로 목에 **비정상 케이스를 한 개씩 심어둔다.**

| 심어둘 것 | 화면에서 확인할 것 |
|---|---|
| `abstained: true` 인 속성 1개 | *"근거 부족 — 판단 보류"* 로 표시되나 |
| `k: null` 인 조건 1개 | *"산출 불가"* 로 표시되나. **0명으로 표시되면 안 된다** |
| `spans: []` 인 글 1편 | *"탐지된 단서 없음"* 이 나오나 (네거티브 컨트롤 시연) |
| 글 0편인 작성자 | 위험도 화면이 에러 없이 뜨나 |

---

## 3. 교체 — 한 번에 하나씩

```python
# apps/analyzer/engines/__init__.py
import os

if os.getenv("ENGINE_MODE", "mock") == "real":
    from .real import detect_spans, specificity, contribution, stage2
else:
    from .mock import detect_spans, specificity, contribution, stage2
```

`real.py`는 B·C·D의 함수를 감싸기만 한다.

```python
# apps/analyzer/engines/real.py
from kopl.c1_span import predict as _c1
from .mock import specificity, contribution, stage2   # 아직 안 온 것은 목을 그대로 쓴다

def detect_spans(post: dict) -> dict:
    return _c1(post["body"], post_id=post["post_id"])
```

**부분 교체가 가능해야 한다.** 위처럼 `mock`에서 import해 두면 c1만 real이고 나머지는 mock인 상태로 돌릴 수 있다. 넷이 다 올 때까지 기다리면 W5가 지나간다.

### 교체 순서와 그때 확인할 것

| 순서 | 교체 | 교체 직후 확인 |
|---|---|---|
| 0 | (교체 없음) | **3화면이 목으로 끝까지 돈다.** 여기까지가 W5 목표 |
| 1 | c1 스팬 | 스팬 위치가 **본문 하이라이트와 한 글자도 안 어긋나나** (offset 기준 사고 1순위) |
| 2 | c2 특정성 | k값과 `basis`가 화면에 뜨나. `null`이 "0명"으로 안 나오나 |
| 3 | c3 기여도 | **부호.** 비공개 추천 글의 `delta`가 음수인가 |
| 4 | c4 2단 | 기권이 표시되나. `verdict`에 신상 단정 문구가 없나 |

**한 번에 하나만 바꾼다.** 둘을 동시에 바꾸면 어느 쪽이 깨졌는지 모른다.

**교체할 때마다 네트워크 탭을 다시 본다** (§5). 모델 로딩 코드가 조용히 허브에서 가중치를 받아오는 일이 실제로 생긴다.

---

## 4. 어댑터 2종

분석기는 **글을 어디서 가져오는지 모른다.** 어댑터가 계약 형식으로 바꿔서 준다.

```python
# apps/analyzer/adapters/sns_adapter.py
import urllib.request, json

def load(author_id: str, base="http://localhost:3000") -> dict:
    with urllib.request.urlopen(f"{base}/api/export/{author_id}") as r:
        return json.load(r)

# apps/analyzer/adapters/file_adapter.py
def load_from_upload(file_obj) -> dict:
    """수동 업로드 경로 — M4 외적 타당성 검증이 이 경로로 돈다.
       .txt(한 줄 = 한 글) / .json(export 형식) 둘 다 받는다"""
    ...
```

**수동 업로드는 공수가 거의 0인데 가치가 크다.** M4에 동의받은 실블로거를 대상으로 검증할 때, 참여자에게 프로그램 설치를 요구하지 않아도 되고 가상 SNS에 계정을 만들 필요도 없다. **W5에 같이 만든다.**

> ⚠️ 업로드된 파일을 **디스크에 쓰지 않는다.** 메모리에서 읽고 버린다. 실블로거의 글이 우리 디스크에 남으면 §6 데이터 원칙(분석 후 즉시 파기)이 깨진다.

---

## 5. "외부 요청 0건"을 실제로 확인하는 법

이건 발표의 결정타이므로 **W5부터 매번 확인하고, 캡처를 남긴다.**

### 절차 (3분)

1. 분석기를 연다 (`http://localhost:8000`)
2. **F12 → Network 탭 → Preserve log 체크 → Clear**
3. 스캔 → 진단 → 조치를 끝까지 돌린다
4. 필터 입력창에 `-localhost` 를 넣는다 (localhost가 아닌 요청만 남는다)
5. **목록이 비어 있어야 한다**
6. 캡처해서 `docs/evidence/network-zero-W05.png` 로 저장

### 코드로도 막는다 — 외부 호출은 파일 하나에만

```python
# apps/analyzer/external.py  ← 외부로 나가는 코드는 전부 이 파일에만 둔다
import os

def external_llm_allowed() -> bool:
    return os.getenv("ALLOW_EXTERNAL_LLM", "false").lower() == "true"

def call_external_llm(payload: dict):
    if not external_llm_allowed():
        raise RuntimeError(
            "ALLOW_EXTERNAL_LLM=false — 외부 전송 차단 (RULES-DO-NOT #2)")
    if "body" in payload or "pseudonymized_body" not in payload:
        raise RuntimeError("원문 전송 시도 — 가명화된 본문만 넘긴다 (§4 원칙 2)")
    ...
```

**파일을 하나로 모으는 것이 핵심이다.** 발표 QnA에서 *"정말 안 나가나요"* 라는 질문에 **파일 하나를 열어 보여주면** 끝난다. 여기저기 흩어져 있으면 증명할 방법이 없다.

### grep으로 계층 경계 검사

```bash
# 분석기가 SNS의 DB나 코드를 직접 건드리지 않는지 — 결과가 0줄이어야 한다
grep -rn "sns\.db\|apps\.sns\|apps/sns" apps/analyzer/ || echo "OK: 경계 유지"

# 분석기가 사용자 글을 파일로 쓰지 않는지 — 나오면 하나씩 확인
grep -rn "open(.*['\"]w\|to_csv\|json\.dump(" apps/analyzer/
```

이 두 줄을 `scripts/check_boundary.sh` 로 만들어두고 **PR마다 돌린다.** 나중에 CI에 넣기도 쉽다.

---

## 6. W5 통합 순서 (하루씩)

| 날 | 할 일 | 끝났다고 판단하는 기준 |
|---|---|---|
| 월 | SNS `export` → 분석기 어댑터 | 분석기 화면에 **글 목록이 뜬다** |
| 화 | 목 엔진 4종 + 스캔 화면 | **위험도 숫자가 하나 뜬다** (가짜여도) |
| 수 | 진단 화면 (7속성 + 근거 + 기권) | 기권한 속성이 *"판단 보류"* 로 뜬다 |
| 목 | 조치 화면 (추천 + 재계산) | *"이 글 3개 → 79.7 → 41"* 형태가 뜬다 |
| 금 | 수동 업로드 경로 + 네트워크 0건 캡처 | 텍스트 파일을 올려도 같은 3화면이 돈다 |

**금요일에 숫자가 전부 가짜여도 W5는 성공이다.** 파이프가 뚫린 것이 산출물이다.

---

## 7. 막히면

| 상황 | 대처 |
|---|---|
| 상대가 함수를 안 준다 | **재촉하지 말고 목으로 진행한다.** 계약대로 만들었으니 오면 붙는다. 수요일 블로커 체크에만 올려둔다 |
| 상대 함수가 계약과 다르게 나온다 | **어댑터에서 변환하지 말고** 계약을 어긴 쪽을 고친다. 변환 코드를 넣기 시작하면 계약이 무의미해진다. 정말 못 고치면 `schema_version`을 올리고 계약을 바꾼다 |
| 실제 모델이 느려서 화면이 멈춘다 | 스캔은 **글 단위로 진행률**을 보여준다. 목표가 CPU 300ms/글이므로 30편이면 10초다. 진행률 없이 10초는 멈춘 것으로 보인다 |
| 모델 로딩에 1분이 걸린다 | 서버 시작 시 **한 번만** 로드한다. 요청마다 로드하면 시연이 안 된다 |
| 스팬 하이라이트가 한 글자씩 밀린다 | `end`가 포함/미포함 어긋난 것이다. `body[start:end] == text` 를 **분석기에서 assert**로 확인하고, 틀리면 B에게 그 예시를 그대로 보낸다 |
| 실제 모델을 붙였더니 외부 요청이 생겼다 | 모델 캐시를 미리 받아두고 **오프라인 모드**로 로드한다 (`HF_HUB_OFFLINE=1`). 시연 PC에서 처음 돌리면 반드시 겪는다 |
| 어디까지 됐는지 헷갈린다 | 목/실제 상태를 **화면 하단에 배지로 표시**한다 (`c1: real · c2: mock …`). 시연 중에도 유용하다 |
