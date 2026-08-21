# 기존 개인정보 탐지 도구 3종 — 설치하고 돌리고 비교하는 법

> 대상: **B 최진필** · 시점: **W2~W3** · 배경은 [B-detector.md §3](../B-detector.md)
> 이 문서 하나로 W2 「기존 도구 3종 실행 환경 + 첫 비교」와 W3 「베이스라인 수치 확정」이 끝난다.

---

## 0. 무엇을 하는가

같은 글에 네 개의 프로그램을 돌려서 **각자 무엇을 잡고 무엇을 놓치는지** 본다.

| 갈래 | 프로그램 | 역할 |
|---|---|---|
| 하한 | 정규식 | 형식이 있는 것만 |
| 기존 도구 ① | Microsoft Presidio | **우리가 이겨야 할 대상** |
| 기존 도구 ② | korean-pii (또는 대체) | 동일 |
| 상한 | LLM 직접 호출 | 도달 가능한 최대치 |

**핵심 질문은 하나다** — *기존 도구가 놓치는 준식별자가 얼마나 되고, 그게 학습으로 도달 가능한가?*

> ⚠️ 이 실험은 **합성 코퍼스에만** 돌린다. RULES-DO-NOT #2의 표에서 *"평가 상한 / 합성 코퍼스 / 제약 없음"* 행이다. `.env`의 `ALLOW_EXTERNAL_LLM=false`는 **런타임에 실사용자 글을 보내는 것**을 막는 스위치이지 이 실험을 막는 것이 아니다. 실험 README에 한 줄 적어둔다.

---

## 1. 준비 (20분)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -U pip

pip install presidio-analyzer presidio-anonymizer
pip install spacy
pip freeze > experiments/exp01-baseline/requirements.txt
```

**버전을 고정해서 커밋한다.** 3주 뒤에 같은 수치가 안 나오면 증빙이 못 된다.

작업 폴더를 먼저 만든다.

```bash
mkdir -p experiments/exp01-baseline/results
cp experiments/_template/README.md experiments/exp01-baseline/README.md
```

---

## 2. 출력 형식을 먼저 통일한다

도구마다 결과 형식이 제각각이다. **비교하려면 같은 모양으로 바꿔야 한다.** 우리 계약([`docs/contracts/span.schema.json`](../../contracts/))과 같은 형식을 쓴다.

```json
{
  "tool": "presidio",
  "post_id": "S01_b07",
  "spans": [
    {"start": 12, "end": 17, "text": "신갈저수지", "type": "LOCATION", "score": 0.85}
  ]
}
```

- `start` 포함, `end` 미포함 (파이썬 슬라이스와 같다: `text[start:end]`)
- **문자 offset**이다. 토큰 인덱스가 아니다
- `type`은 도구마다 이름이 다르다. **바꾸지 말고 원래 이름 그대로 담는다.** 우리 유형과의 대응은 §7에서 매핑표로 따로 만든다

각 도구마다 `run_<도구>.py` 를 하나씩 만들고, 전부 이 형식의 JSONL을 뱉게 한다.

```
experiments/exp01-baseline/
├─ run_regex.py
├─ run_presidio.py
├─ run_koreanpii.py
├─ run_llm.py
├─ compare.py
└─ results/
   ├─ regex.jsonl  presidio.jsonl  koreanpii.jsonl  llm.jsonl
   └─ metrics.json
```

---

## 3. 규칙 기반 — 성능의 하한

정규식으로 **형식이 있는 것**만 잡는다. 30분이면 된다.

```python
# run_regex.py
import re, json

PATTERNS = {
    "RRN":        r"\b\d{6}[-\s]?[1-8]\d{6}\b",                       # 주민등록번호
    "PHONE_MOB":  r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b",        # 휴대전화
    "PHONE_TEL":  r"\b0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4])[-\s.]?\d{3,4}[-\s.]?\d{4}\b",
    "EMAIL":      r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "CARD":       r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "BIZNO":      r"\b\d{3}-\d{2}-\d{5}\b",                           # 사업자등록번호
    "IP":         r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "ACCOUNT":    r"\b\d{2,6}-\d{2,6}-\d{2,6}\b",                     # ⚠️ 오탐 많음
}

def detect(text):
    out = []
    for typ, pat in PATTERNS.items():
        for m in re.finditer(pat, text):
            out.append({"start": m.start(), "end": m.end(),
                        "text": m.group(), "type": typ, "score": 1.0})
    return out
```

> ⚠️ **`ACCOUNT` 패턴은 날짜를 잡는다.** `2026-08-24`가 그대로 걸린다. **이게 규칙 기반이 하한인 이유를 보여주는 좋은 예**이니 지우지 말고 **오탐 사례로 기록**한다. 리포트에 한 줄 들어갈 재료다.

**계좌번호는 은행마다 자릿수가 다르다.** 완전한 패턴은 없다. 합성 코퍼스에 A가 어떤 형식으로 심었는지 **먼저 물어보고** 맞춘다.

---

## 4. Presidio — 우리가 이겨야 할 대상

### 4.1 왜 그냥은 안 되나

Presidio의 인식기는 두 종류다.

| 종류 | 예 | 한국어에서 |
|---|---|---|
| **규칙·체크섬 기반** | 이메일, IP, 신용카드 | **언어와 무관하게 동작한다** |
| **NER 기반** | 사람 이름, 지명, 조직 | **NLP 엔진이 한국어를 알아야 동작한다** |

기본 설정은 영어 모델을 쓴다. 그대로 돌리면 지명·이름을 못 잡는데, **그건 우리가 이긴 게 아니라 설정을 안 한 것**이다. 심사에서 제일 먼저 깨질 지점이다.

### 4.2 세 단계로 시도한다

**① 한국어 spaCy 모델 붙이기 (가장 정공법)**

```bash
python -m spacy download ko_core_news_lg
```

```python
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

conf = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "ko", "model_name": "ko_core_news_lg"}],
}
nlp_engine = NlpEngineProvider(nlp_configuration=conf).create_engine()
analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["ko"])

results = analyzer.analyze(text="집 근처 신갈저수지 다녀왔어요", language="ko")
for r in results:
    print(r.entity_type, r.start, r.end, r.score)
```

한국어 spaCy 모델은 형태소 분석기(mecab 계열)를 요구할 수 있다. **Windows에서 설치가 까다로운 대표 지점**이다. 30분 넘게 붙잡지 말고 ②로 간다.

**② 규칙 기반 인식기만 쓰기**

NLP 엔진 없이도 이메일·IP·카드 같은 패턴 인식기는 동작한다. NER 계열이 빠졌다는 사실을 **명시하고** 돌린다.

**③ 한국어 인식기를 직접 추가하기**

`PatternRecognizer`로 한국 전화번호·주민번호 패턴을 붙여 준다. 이건 "Presidio에 우리가 손을 댄 것"이므로 **그 사실을 리포트에 적는다** — 오히려 *"기존 도구를 최대한 유리하게 세팅했는데도 준식별자는 못 잡았다"* 는 더 강한 근거가 된다.

```python
from presidio_analyzer import PatternRecognizer, Pattern

kr_phone = PatternRecognizer(
    supported_entity="PHONE_NUMBER",
    supported_language="ko",
    patterns=[Pattern(name="kr_mobile",
                      regex=r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}", score=0.8)],
)
analyzer.registry.add_recognizer(kr_phone)
```

### 4.3 확인할 것 두 가지

- **전화번호 인식기의 기본 지역이 무엇인지.** Presidio의 전화번호 인식은 국가 설정에 따라 결과가 달라진다. 한국 번호가 안 잡히면 이것부터 본다.
- **설치한 presidio 버전.** 버전에 따라 `NlpEngineProvider` 인자 이름이 바뀐 적이 있다. 에러가 나면 설치된 버전의 공식 문서를 본다. **버전을 `requirements.txt`에 고정해서 커밋한다.**

### 4.4 어디까지 갔는지 반드시 기록

```markdown
## Presidio 설정
- presidio-analyzer 2.x.x
- NLP 엔진: ko_core_news_lg / (또는) 규칙 인식기만
- 추가한 인식기: 한국 휴대전화 패턴 1종
- 시도했으나 실패: (있으면 적는다)
```

**"설정이 어려웠다"와 "탐지를 못 한다"를 분리해서 적는다.** 전자는 도구의 접근성 한계고 후자는 성능 한계다. 섞으면 우리 주장이 약해진다.

---

## 5. korean-pii — 또는 대체 도구

[plan.md 부록](../../plan.md)에 저장소 링크가 있다. **README대로 설치하고, 그 API 그대로 쓴다.** 이 문서에 미리 코드를 적어두지 않는 이유는 저장소마다 인터페이스가 다르고, 추측해서 적으면 틀리기 때문이다.

**설치가 안 되거나 유지보수가 끊긴 것으로 보이면** 대체를 쓴다.

| 대체 후보 | 성격 | 주의 |
|---|---|---|
| 공개 한국어 NER 모델 (HuggingFace) | 명시 개체명 탐지 | **라이선스를 먼저 본다.** 대회용 데이터로 학습된 것은 피한다 |
| KLUE-NER 계열 공개 체크포인트 | 동일 | KLUE-NER 자체는 CC BY-SA 4.0 |

**바꿨으면 바꾼 이유를 적는다.** "기존 도구" 칸이 비면 비교의 의미가 사라진다.

> ⚠️ 대체 도구도 **명시 PII·개체명 탐지기**여야 한다. 준식별자 탐지기를 골라오면 비교 대상이 아니라 경쟁 모델이 된다.

---

## 6. LLM 직접 — 성능의 상한

```python
PROMPT = """다음 블로그 글에서 글쓴이의 신상을 좁힐 수 있는 표현 구간을 모두 찾아라.
이름·전화번호 같은 명시적 정보뿐 아니라, 나이·거주지·직업·가족·통근을
간접적으로 드러내는 표현도 포함한다.

각 구간에 대해 아래 JSON 배열로만 답하라. 설명을 붙이지 마라.
[{"text": "원문 그대로의 구간", "type": "AGE|LOC|JOB|FAMILY|COMMUTE|OTHER"}]

글:
---
{body}
---"""
```

**offset은 모델에게 묻지 않는다.** LLM은 글자 위치를 자주 틀린다. `text`만 받아서 우리가 `str.find()`로 위치를 계산한다. 같은 문자열이 여러 번 나오면 등장 순서대로 매칭한다.

```python
def to_spans(text, items):
    out, cursor = [], 0
    for it in items:
        i = text.find(it["text"], cursor)
        if i < 0:
            i = text.find(it["text"])      # 순서가 어긋나면 처음부터 다시
        if i < 0:
            continue                        # 원문에 없는 것을 지어냈다 — 버리고 건수를 센다
        out.append({"start": i, "end": i + len(it["text"]),
                    "text": it["text"], "type": it["type"], "score": 1.0})
        cursor = i + len(it["text"])
    return out
```

**원문에 없는 구간을 지어낸 건수를 세서 기록한다.** LLM 상한의 한계를 보여주는 수치가 된다.

> ⚠️ **상한은 골드셋(사람이 검수한 것)에서만 잰다.**
> A의 교사 LLM이 붙인 라벨 전체를 정답으로 쓰면 *"교사가 만든 답을 교사가 맞힌다"* 가 되어 상한이 부풀려진다. 가능하면 **교사 LLM과 다른 모델**을 상한 측정에 쓴다. 못 하면 최소한 **blind 200**에서 잰다.

**크레딧 관리**: 200편 × 1회면 충분하다. 재현을 위해 **응답 원문을 `results/llm_raw/`에 저장**해두면 재호출 없이 다시 계산할 수 있다. `temperature=0`으로 고정한다.

---

## 7. 비교 — W2판과 W3판이 다르다

### 7.1 W2 — 미탐 목록 (골드셋이 아직 없다)

정답표가 없으니 **F1은 못 낸다.** 대신 **손으로 20편을 본다.**

```bash
python run_regex.py     --in data/corpus/v0/posts/ --out results/regex.jsonl
python run_presidio.py  --in data/corpus/v0/posts/ --out results/presidio.jsonl
python run_koreanpii.py --in data/corpus/v0/posts/ --out results/koreanpii.jsonl
```

그다음 20편을 골라 **표 하나를 손으로 채운다.**

| 글 | 준식별자로 보이는 구간 | 규칙 | Presidio | korean-pii | 등급 |
|---|---|---|---|---|---|
| S01_b07 | 신갈저수지 | ✗ | ✗ | ✗ | inferential |
| S01_b07 | 집 근처 | ✗ | ✗ | ✗ | inferential |
| S03_b02 | 마흔여덟 | ✗ | ✗ | ✗ | implicit |
| S05_b11 | 010-1234-5678 | ○ | ○ | ○ | explicit |

**세 칸이 전부 ✗인 줄이 우리 존재 이유다.** 이 표를 `experiments/exp01-baseline/README.md`에 그대로 넣는다.

**완료 기준**: 미탐 스팬 목록 파일 1건 + 세 도구의 출력 JSONL 3건. 수치가 아니라 목록이면 된다.

### 7.2 W3 — 수치 (골드셋이 있다)

```python
# compare.py — 핵심 로직
def exact_match(a, b):
    return a["start"] == b["start"] and a["end"] == b["end"]

def missed_by_tools(gold_spans, tool_spans_list):
    """기존 도구 셋 중 아무도 못 잡은 골드 스팬"""
    missed = []
    for g in gold_spans:
        if not any(exact_match(g, t) for tool in tool_spans_list for t in tool):
            missed.append(g)
    return missed
```

**세 가지 수치를 낸다.**

| 수치 | 계산 | 뜻 |
|---|---|---|
| **미탐 공간 크기** | `len(missed) / len(gold)` | 기존 도구가 놓친 비율. **분모가 여기서 나온다** |
| **도달 가능성** | `LLM이 missed에서 잡은 수 / len(missed)` | 학습으로 도달 가능한지 |
| (W7) **추가 탐지율** | `우리 모델이 missed에서 잡은 수 / len(missed)` | 최종 수치 |

**반드시 등급별로 쪼갠다.**

```json
{
  "measured_at": "2026-09-03",
  "data_version": "corpus-v0-gold-610",
  "scoring": "exact_match",
  "gold_spans": 610,
  "by_level": {
    "explicit":    {"gold": 180, "missed_by_tools": 22,  "missed_rate": 0.122,
                    "llm_recovers": 20, "reachability": 0.909},
    "implicit":    {"gold": 320, "missed_by_tools": 298, "missed_rate": 0.931,
                    "llm_recovers": 214, "reachability": 0.718},
    "inferential": {"gold": 110, "missed_by_tools": 108, "missed_rate": 0.982,
                    "llm_recovers": 61,  "reachability": 0.565}
  },
  "tools": {"regex": "...", "presidio": "...", "koreanpii": "..."},
  "note": "위 숫자는 형식 예시다. 실제 측정치로 덮어쓴다."
}
```

> ⚠️ 위 JSON의 값은 **형식을 보여주는 예시**이고 측정치가 아니다. 실제 값으로 덮어쓸 때 `note` 줄을 지운다.

**유형 이름 매핑표를 함께 만든다.** Presidio의 `LOCATION`이 우리 `LOC_FACILITY`와 같은지 다른지를 정해야 "잡았다/못 잡았다"를 판정할 수 있다. 매핑은 `results/type_mapping.md`에 표로 남기고, **느슨하게 잡는다** — 기존 도구에 유리하게 판정해야 격차 주장이 강해진다.

### 7.3 판정

| 결과 | 뜻 | 다음 |
|---|---|---|
| implicit·inferential의 미탐율이 높고 LLM 도달 가능성도 높다 | **주제 성립** | 그대로 진행 |
| 미탐율은 높은데 LLM도 못 잡는다 | 학습 신호가 약하다 | A와 단서 설계 재검토 · 목표치 하향 |
| explicit만 미탐 | 설정 문제일 가능성 | **§4를 다시 본다** |
| 전 등급에서 미탐율이 낮다 | 🔴 **기존 도구로 충분하다** | **즉시 팀 공유 → W4 설계서에서 주제 재검토** |

---

## 8. 기록

`experiments/exp01-baseline/README.md`에 [양식](../../../experiments/_template/README.md)대로 채운다. 빠뜨리기 쉬운 칸.

| 칸 | 적을 것 |
|---|---|
| 측정일 | 실행한 날짜 |
| 데이터 버전 | `corpus-v0` / 골드셋 스팬 수 |
| 도구 버전 | presidio 버전, spaCy 모델, LLM 모델명 |
| 채점 기준 | **정확 일치**임을 명시 |
| 한계 | 유형 매핑의 자의성, Presidio 한국어 설정 수준, LLM 환각 건수 |

```bash
git add experiments/exp01-baseline/
git commit -m "exp(c1): 베이스라인 3종 측정 — 기존 도구 미탐 공간 XX%, LLM 상한이 그중 XX% 회수"
```

**`results/`에는 수치만 커밋한다.** 원문·LLM 응답 원문은 `.gitignore` 대상이거나 로컬에만 둔다.

---

## 9. 막히면

| 상황 | 대처 |
|---|---|
| spaCy 한국어 모델 설치가 안 된다 | 30분 넘기지 말고 §4.2 ②로. **실패 사실을 기록**하고 넘어간다 |
| Presidio가 아무것도 못 잡는다 | `language="ko"`를 넘겼는지, `supported_languages`에 `"ko"`가 있는지 확인. 기본값은 `"en"`이다 |
| korean-pii가 설치가 안 된다 | §5 대체 후보. **이유를 기록**한다 |
| LLM이 JSON이 아닌 걸 뱉는다 | `temperature=0` · 프롬프트 끝에 *"JSON 배열만 출력"* 반복 · 앞뒤 설명을 정규식으로 잘라낸다 |
| LLM이 원문에 없는 구간을 만든다 | `find()`가 실패하면 버리고 **건수를 센다.** 그 자체가 결과다 |
| 유형 이름이 서로 안 맞는다 | 매핑표를 만들되 **기존 도구에 유리하게** 느슨히 잡는다 |
| 결과가 도구마다 너무 달라 비교가 안 된다 | 정상이다. 그래서 §2의 공통 형식으로 강제 변환하는 것이다 |
| 격차가 안 보인다 | **숨기지 말고 즉시 팀에 알린다.** 판정에 시간이 필요하다 |
