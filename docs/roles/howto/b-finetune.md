# 한국어 인코더 파인튜닝 — 데이터 로더부터 지연 측정까지

> 대상: **B 최진필** · 시점: **W4~W7** · 배경은 [B-detector.md §2·§5](../B-detector.md)
> **파인튜닝을 처음 하는 사람 기준**으로 썼다. 개념은 [B-detector.md §2](../B-detector.md)에 있으니 먼저 읽는다.

---

## 0. 전체 그림

```
A의 코퍼스(JSONL)          ①            ②              ③              ④
 문자 offset 스팬  →  BIO 태그  →  토큰 정렬  →  학습  →  스팬 복원 → 채점
                                                              ↓
                                                      추론 함수 (E에게)
```

**막히면 거의 항상 ①~②다.** ③④는 정형화되어 있다. 그래서 이 문서의 절반이 데이터 처리에 쓰였다.

**작업 순서** — 이 순서를 지키면 며칠을 아낀다.

| 순서 | 무엇 | 시간 |
|---|---|---|
| 1 | 환경 확인 (§1) | 20분 |
| 2 | BIO 변환 + **역변환 검증** (§2) | 2시간 |
| 3 | 토큰 정렬 (§3) | 1시간 |
| 4 | ⭐ **100건 과적합 테스트** (§5) | 30분 |
| 5 | 전체 학습 (§6) | 수 시간 (기다리기만) |
| 6 | 채점 (§7) · 재개 구조 (§8) · 추론 함수 (§9) | 하루 |

**4번을 건너뛰지 않는다.** 전체 학습을 먼저 돌리면 실패했을 때 원인이 데이터인지 하이퍼파라미터인지 구분이 안 된다.

---

## 1. 환경 (20분)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install torch transformers datasets seqeval accelerate
pip freeze > requirements.txt
```

확인 세 줄. **셋 다 통과해야 다음으로 간다.**

```python
import torch
print(torch.cuda.is_available(), torch.cuda.get_device_name(0))   # ① True + GPU 이름

from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("monologg/koelectra-base-v3-discriminator", use_fast=True)
print(tok.is_fast)                                                # ② True 여야 한다

print(tok("집 근처 신갈저수지 다녀왔어요", return_offsets_mapping=True)["offset_mapping"])
                                                                  # ③ 좌표 목록이 나와야 한다
```

> ⚠️ **②가 `False`면 이 문서의 방식이 통째로 안 된다.** `return_offsets_mapping`은 fast 토크나이저에만 있다. `use_fast=True`로 로드가 안 되면 `pip install tokenizers`를 확인하고, 그래도 안 되면 다른 백본(KLUE-RoBERTa 등)을 쓴다.

---

## 2. 데이터 — 문자 offset을 BIO로

### 2.1 A에게서 받는 형식

```json
{"post_id": "S01_b07", "persona_id": "S01",
 "body": "집 근처라 자주 가는 신갈저수지 조황입니다. 마흔여덟 되니…",
 "spans": [
   {"start": 0,  "end": 5,  "text": "집 근처", "type": "REL_HOME",     "level": "inferential"},
   {"start": 12, "end": 17, "text": "신갈저수지", "type": "LOC_FACILITY", "level": "inferential"},
   {"start": 25, "end": 29, "text": "마흔여덟", "type": "AGE",          "level": "implicit"}
 ]}
```

**받자마자 검사한다.** 형식이 틀린 데이터로 학습하면 §10의 "F1이 0" 상황이 된다.

```python
def sanity(rec):
    problems = []
    for sp in rec["spans"]:
        if rec["body"][sp["start"]:sp["end"]] != sp["text"]:
            problems.append(f"offset 불일치: {sp}")          # ← 가장 흔한 사고
        if sp["start"] >= sp["end"]:
            problems.append(f"길이 0: {sp}")
    # 겹침 검사 — 스키마상 금지다
    ss = sorted(rec["spans"], key=lambda x: x["start"])
    for a, b in zip(ss, ss[1:]):
        if b["start"] < a["end"]:
            problems.append(f"겹침: {a} / {b}")
    return problems
```

**offset 불일치가 한 건이라도 나오면 A에게 즉시 알린다.** 유니코드 정규화나 개행 처리에서 어긋나는 경우가 많고, 코퍼스 전체가 밀려 있을 수 있다.

### 2.2 라벨 목록 만들기

```python
TYPES = ["LOC_FACILITY", "AGE", "JOB", "FAMILY", "COMMUTE", "REL_HOME", "REL_COMMUTE"]

LABELS   = ["O"] + [f"{p}-{t}" for t in TYPES for p in ("B", "I")]
label2id = {l: i for i, l in enumerate(LABELS)}
id2label = {i: l for l, i in label2id.items()}
```

유형이 바뀌면 **`TYPES` 한 줄만 고친다.** 그래서 유형이 확정되기 전에도 파이프라인을 만들 수 있다.

### 2.3 데이터 나누기 — **인물 단위로 자른다**

| 쓰임 | 데이터 |
|---|---|
| 학습 | 교사 LLM 자동 라벨 코퍼스 |
| 개발 (하이퍼파라미터 조정) | 골드셋 일부 |
| **최종 보고** | 골드셋 나머지 + **blind 200** |

> ⚠️ **`persona_id` 단위로 나눈다. 글(`post_id`) 단위가 아니다.**
> 같은 인물의 다른 글이 학습셋에 있으면 모델이 **내용이 아니라 그 사람의 문체를 외운다.** A가 인물마다 종결어미·이모지·말버릇을 다르게 설계해 두었기 때문에 이 누수는 특히 크게 나온다. F1이 부풀려지고 W7에 실제보다 좋은 수치를 보고하게 된다.

```python
import random
personas = sorted({r["persona_id"] for r in records})
random.Random(42).shuffle(personas)
n = len(personas)
dev_p  = set(personas[:int(n*0.1)])
test_p = set(personas[int(n*0.1):int(n*0.2)])
train  = [r for r in records if r["persona_id"] not in dev_p | test_p]
```

**시드를 고정하고 분할 결과를 파일로 저장한다.** 매번 다시 나누면 수치를 비교할 수 없다.

---

## 3. 토큰 정렬 — 여기가 한국어의 함정이다

한국어는 조사가 붙는다. "신갈저수지에서"를 토크나이저는 `신갈` `##저수지` `##에서` 로 쪼갤 수 있는데 우리 스팬은 "신갈저수지"까지다. **토큰 경계와 스팬 경계가 어긋나는 게 기본**이다.

```python
def encode(rec, tokenizer, max_length=256):
    enc = tokenizer(rec["body"], truncation=True, max_length=max_length,
                    return_offsets_mapping=True)
    labels = []
    for (s, e) in enc["offset_mapping"]:
        if s == e:                       # [CLS] [SEP] [PAD] → 손실에서 제외
            labels.append(-100)
            continue
        tag = "O"
        for sp in rec["spans"]:
            if s < sp["end"] and e > sp["start"]:          # ← 겹치면 그 스팬 소속
                tag = ("B-" if s <= sp["start"] else "I-") + sp["type"]
                break
        labels.append(label2id[tag])
    enc["labels"] = labels
    enc.pop("offset_mapping")
    return enc
```

**왜 "완전히 포함"이 아니라 "겹치면"인가.** `s >= sp["start"] and e <= sp["end"]` 로 쓰면 `##에서` 처럼 스팬 밖으로 삐져나온 토큰이 `O`가 되고, 조사가 붙은 스팬이 통째로 사라진다. 한국어에서는 그런 스팬이 상당수다. **조사를 조금 더 잡는 쪽**이 안전하다.

**`-100`이 무엇인가**: 파이토치 손실 함수가 무시하는 특수값이다. 특수 토큰과 패딩에 이걸 넣어야 모델이 "[CLS]는 O다" 같은 걸 배우느라 힘을 쓰지 않는다.

### 3.1 잘림 검사

`max_length=256`이면 긴 글의 뒷부분 스팬이 통째로 사라진다.

```python
def lost_span_rate(records, tokenizer, max_length=256):
    total = lost = 0
    for r in records:
        enc = tokenizer(r["body"], truncation=True, max_length=max_length,
                        return_offsets_mapping=True)
        last = max(e for s, e in enc["offset_mapping"])
        for sp in r["spans"]:
            total += 1
            if sp["start"] >= last:
                lost += 1
    return lost / total if total else 0.0
```

| 결과 | 조치 |
|---|---|
| 5% 미만 | 그대로 간다. **리포트에 비율을 적는다** |
| 5~15% | `max_length`를 384로 (VRAM 여유가 있으면) |
| 15% 초과 | 슬라이딩 윈도우 — `return_overflowing_tokens=True, stride=64` |

### 3.2 역변환 — BIO를 다시 스팬으로

학습이 끝나면 모델이 뱉는 BIO를 다시 구간으로 되돌려야 한다. **지금 만들어서 검증까지 해둔다.**

```python
def decode(text, offsets, tags):
    spans, cur = [], None
    for (s, e), tag in zip(offsets, tags):
        if s == e:
            continue
        if tag.startswith("B-"):
            if cur: spans.append(cur)
            cur = {"start": s, "end": e, "type": tag[2:]}
        elif tag.startswith("I-") and cur and cur["type"] == tag[2:]:
            cur["end"] = e
        else:
            if cur: spans.append(cur)
            cur = None
    if cur: spans.append(cur)
    for sp in spans:
        sp["text"] = text[sp["start"]:sp["end"]]
    return spans
```

**⭐ 왕복 테스트 — 이걸 통과해야 학습으로 넘어간다.**

```python
# 정답 스팬 → BIO → 다시 스팬 → 원래와 비교
ok = near = bad = 0
for r in records[:200]:
    enc  = tokenizer(r["body"], truncation=True, max_length=256,
                     return_offsets_mapping=True)
    tags = [id2label[i] if i >= 0 else "O" for i in encode(r, tokenizer)["labels"]]
    back = decode(r["body"], enc["offset_mapping"], tags)
    for g in r["spans"]:
        m = [b for b in back if b["start"] < g["end"] and b["end"] > g["start"]]
        if   not m:                                        bad  += 1
        elif m[0]["start"] == g["start"] and m[0]["end"] == g["end"]: ok += 1
        else:                                              near += 1
print(ok, near, bad)
```

| 결과 | 판정 |
|---|---|
| `bad`가 0에 가깝다 | ✅ 정상 |
| `near`가 있다 | 정상이다 — 조사가 딸려 오는 것. **몇 글자씩 어긋나는지 세어 기록한다** |
| `bad`가 전체의 10% 이상 | 🔴 정렬 로직이 잘못됐다. 학습으로 넘어가지 않는다 |

`near`가 많으면 **정확 일치 F1의 상한이 그만큼 깎인다.** 모델이 완벽해도 도달할 수 없는 천장이다. 이 값을 미리 재두면 W7에 *"정확 일치 F1 0.84는 파이프라인 상한 0.91 대비"* 라고 말할 수 있다.

---

## 4. Dataset 만들기

```python
from datasets import Dataset

def to_dataset(records, tokenizer):
    rows = [encode(r, tokenizer) for r in records]
    return Dataset.from_list(rows)

train_ds = to_dataset(train, tok)
dev_ds   = to_dataset(dev,   tok)
```

패딩은 콜레이터가 처리한다. **직접 패딩하지 않는다** — 라벨에 `-100`을 채워야 하는데 손으로 하면 틀린다.

```python
from transformers import DataCollatorForTokenClassification
collator = DataCollatorForTokenClassification(tokenizer=tok)
```

---

## 5. ⭐ 100건 과적합 테스트 — 먼저 이걸 통과시킨다

**학습 데이터 100건으로 학습하고 같은 100건으로 평가한다.**

```python
tiny = train[:100]
tiny_ds = to_dataset(tiny, tok)

args = TrainingArguments(output_dir="out/tiny", num_train_epochs=20,
                         per_device_train_batch_size=8, learning_rate=5e-5,
                         logging_steps=10, report_to=[])
Trainer(model=model, args=args, train_dataset=tiny_ds,
        eval_dataset=tiny_ds, data_collator=collator,
        compute_metrics=compute_metrics).train()
```

| 결과 | 뜻 | 다음 |
|---|---|---|
| F1 **≥ 0.9** | 파이프라인이 정상이다 | 전체 학습으로 |
| F1이 **0** | **라벨 정렬 버그** | §3으로 돌아간다. 모델 문제가 아니다 |
| F1이 0.3~0.6에서 멈춘다 | 라벨이 일부만 붙었다 | `labels`에서 `-100`·`O`를 뺀 개수를 센다 |
| 손실이 `nan` | 발산 | 학습률을 `2e-5`로 |

**모델은 100건이면 통째로 외울 수 있다.** 외우지 못한다면 배울 것이 잘못 들어간 것이다. **30분이면 끝나고, 며칠을 아낀다.**

---

## 6. 학습

```python
from transformers import AutoModelForTokenClassification, TrainingArguments, Trainer

model = AutoModelForTokenClassification.from_pretrained(
    "monologg/koelectra-base-v3-discriminator",
    num_labels=len(LABELS), id2label=id2label, label2id=label2id)

args = TrainingArguments(
    output_dir="out/koelectra-v1",
    learning_rate=3e-5,
    num_train_epochs=3,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=32,
    gradient_accumulation_steps=1,
    warmup_ratio=0.1,
    weight_decay=0.01,
    fp16=True,
    logging_steps=50,
    eval_strategy="epoch",            # ← 버전에 따라 evaluation_strategy
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="recall",   # 방어 도구는 놓치지 않는 쪽이 먼저다
    seed=42,
    report_to=[],
)

trainer = Trainer(model=model, args=args,
                  train_dataset=train_ds, eval_dataset=dev_ds,
                  data_collator=collator, compute_metrics=compute_metrics)
trainer.train()
trainer.save_model("out/koelectra-v1/best")
tok.save_pretrained("out/koelectra-v1/best")
```

**두 가지만 짚는다.**

- `eval_strategy` — transformers 버전에 따라 `evaluation_strategy`다. **에러 메시지가 어느 이름인지 알려준다.** 고친 뒤 `requirements.txt`에 버전을 고정한다.
- `metric_for_best_model="recall"` — plan.md §4 원칙 3이 *"맞히기가 아니라 놓치지 않기"* 다. F1으로 고르면 정밀도가 높은(= 소극적인) 체크포인트가 뽑힌다. **이 선택을 실험 README에 적는다.**

**학습 중에 볼 것**: 손실이 내려가는가, `eval_recall`이 0이 아닌가. 첫 에폭 끝에 `eval_recall`이 0이면 **바로 중단하고 §5로 돌아간다.** 3에폭을 기다리지 않는다.

---

## 7. 채점

### 7.1 학습 중 지표 — seqeval

```python
import numpy as np
from seqeval.metrics import precision_score, recall_score, f1_score

def compute_metrics(p):
    logits, labels = p
    preds = np.argmax(logits, axis=-1)
    true, pred = [], []
    for pr, la in zip(preds, labels):
        t, q = [], []
        for pi, li in zip(pr, la):
            if li == -100:
                continue
            t.append(id2label[li]); q.append(id2label[pi])
        true.append(t); pred.append(q)
    return {"precision": precision_score(true, pred),
            "recall":    recall_score(true, pred),
            "f1":        f1_score(true, pred)}
```

`seqeval`은 **토큰이 아니라 스팬 단위로** 센다. 그래서 §2.3의 "전부 O로 찍으면 0.97" 문제가 여기서는 안 생긴다.

기본 모드는 관대한 편이다. 리포트용 수치는 엄격 모드로 다시 낸다.

```python
from seqeval.scheme import IOB2
f1_score(true, pred, mode="strict", scheme=IOB2)
```

### 7.2 리포트용 지표 — 스팬 단위로 직접 센다

seqeval은 BIO만 본다. 우리는 **등급별**로도 내야 하는데 등급은 BIO 태그에 없다. 그래서 §3.2의 `decode()`로 스팬을 복원한 뒤 직접 센다.

```python
def score(gold, pred, mode="exact"):
    def match(a, b):
        if a["type"] != b["type"]:
            return False
        if mode == "exact":
            return a["start"] == b["start"] and a["end"] == b["end"]
        return a["start"] < b["end"] and b["start"] < a["end"]      # 부분 일치(겹침)

    used, tp = set(), 0
    for g in gold:
        for j, p in enumerate(pred):
            if j in used or not match(g, p):
                continue
            used.add(j); tp += 1; break
    fp, fn = len(pred) - tp, len(gold) - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec  = tp / (tp + fn) if tp + fn else 0.0
    f1   = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}
```

**등급별 평가 규칙** — 예측 스팬에는 등급이 없으므로 규칙을 정해야 한다.

> **그 등급만 남긴 평가셋에서 잰다.** 골드에서 해당 등급만 남기고, 예측 중 *다른 등급의 골드와 정확히 일치하는 것*은 채점에서 제외한다(오탐으로 세지 않는다). 남은 예측만 FP로 센다.

이 규칙을 **리포트에 그대로 적는다.** 안 적으면 등급별 정밀도가 왜 그렇게 나왔는지 설명할 수 없다.

### 7.3 리포트에 들어갈 표

| | 정확 일치 F1 | 재현율 | 부분 일치 F1 | 골드 스팬 수 |
|---|---|---|---|---|
| **explicit** (목표 ≥ 0.80) | | | | |
| **implicit** (목표 = IAA × 0.8) | | | | |
| inferential | | | | |
| 전체 | | | | |

**함께 적는 것**: 측정일 · 데이터 버전 · 모델 버전 · 하드웨어 · 시드 · **채점 기준** · IAA 값 · §3.2의 파이프라인 상한.

---

## 8. 중간 저장과 재개 — Kaggle 대비

Kaggle 무료 GPU는 세션이 끊긴다. **끊기는 것을 전제로 짠다.**

```python
args = TrainingArguments(
    ...,
    save_strategy="steps",
    save_steps=200,
    save_total_limit=3,          # 디스크 용량 제한이 있다
)

trainer.train(resume_from_checkpoint=True)   # 마지막 체크포인트에서 이어서
```

| 항목 | 방법 |
|---|---|
| 체크포인트 위치 | Kaggle은 `/kaggle/working/` (세션 종료 시 output만 남는다) |
| 세션 밖으로 빼기 | HuggingFace Hub **private** 저장소로 push. **repo에 커밋하지 않는다** |
| 재개 확인 | 일부러 한 번 죽여보고 `resume_from_checkpoint=True`가 동작하는지 **W4에 확인해 둔다** |

> ⚠️ **가중치는 repo에 커밋하지 않는다.** `.gitignore`가 `*.safetensors` `*.bin` `/models/*`를 막는다. [`models/registry.md`](../../../models/registry.md)에 이름·베이스·방식·위치·학습일·데이터 버전·지표 한 행을 적는 것이 전부다.

---

## 9. 추론 함수 — E에게 넘길 것

E는 이 클래스 하나만 있으면 웹앱에 붙일 수 있다. **모델 내부를 몰라도 되게 만든다.**

```python
# src/kopl/c1_span/detector.py
import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification

class SpanDetector:
    def __init__(self, model_dir, device="cpu", max_length=256, threshold=0.0):
        self.tok = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
        self.model = AutoModelForTokenClassification.from_pretrained(model_dir)
        self.model.eval().to(device)
        self.device, self.max_length, self.threshold = device, max_length, threshold
        self.id2label = self.model.config.id2label
        self.version = model_dir.rstrip("/").split("/")[-1]

    @torch.no_grad()
    def detect(self, text, post_id=None):
        enc = self.tok(text, truncation=True, max_length=self.max_length,
                       return_offsets_mapping=True, return_tensors="pt")
        offsets = enc.pop("offset_mapping")[0].tolist()
        enc = {k: v.to(self.device) for k, v in enc.items()}
        probs = self.model(**enc).logits.softmax(-1)[0]
        ids   = probs.argmax(-1).tolist()
        conf  = probs.max(-1).values.tolist()
        tags  = [self.id2label[i] for i in ids]
        spans = decode(text, offsets, tags)          # §3.2
        for sp in spans:
            sp["score"] = round(min(c for (s, e), c in zip(offsets, conf)
                                    if s >= sp["start"] and e <= sp["end"]), 4)
        return {"post_id": post_id, "model_version": self.version,
                "spans": [s for s in spans if s["score"] >= self.threshold]}
```

**출력이 [`docs/contracts/span.schema.json`](../../contracts/)과 일치하는지 테스트를 하나 둔다.** 계약이 목요일에 잠기므로, 계약을 깨는 변경은 2명 승인이 필요하다.

`level`(등급)은 모델이 예측하지 않는다 — 골드셋의 속성이지 출력이 아니다. **계약에 `level`이 있다면 A·C와 어떻게 채울지 W2에 정한다.**

### 9.1 CPU 지연 측정

```python
import time, torch

torch.set_num_threads(4)                       # 스레드 수를 고정하고 기록한다
det = SpanDetector("out/koelectra-v1/best", device="cpu")
sample = open("data/corpus/v0/sample_median.txt", encoding="utf-8").read()

for _ in range(5):                             # 워밍업
    det.detect(sample)

ts = []
for _ in range(50):
    t0 = time.perf_counter()
    det.detect(sample)                         # 토크나이즈·추론·스팬 복원 전부 포함
    ts.append((time.perf_counter() - t0) * 1000)

ts.sort()
print(f"median {ts[len(ts)//2]:.1f}ms  p90 {ts[int(len(ts)*0.9)]:.1f}ms")
```

**함께 기록한다**: CPU 모델명 · 스레드 수 · 입력 글자 수 · `max_length` · 워밍업 횟수 · 표본 수.

### 9.2 300ms를 못 맞추면

| 순서 | 조치 | 기대 | 대가 |
|---|---|---|---|
| 1 | `max_length` 256 → 192 | 비례해서 빨라진다 | 긴 글 잘림 ↑ |
| 2 | 스레드 수 늘리기 | 환경에 따라 | 사용자 PC를 가정할 수 없다 → **보수적으로 4** |
| 3 | **동적 양자화 (int8)** | CPU에서 크게 빨라진다 | **F1이 떨어질 수 있다 → 반드시 다시 잰다** |
| 4 | ONNX Runtime으로 내보내기 | 추가 개선 | 변환 작업 필요 |
| 5 | 더 작은 백본 (small 계열) | 큼 | F1 하락 |

```python
qmodel = torch.quantization.quantize_dynamic(
    det.model, {torch.nn.Linear}, dtype=torch.qint8)
```

> ⚠️ **양자화 후 F1을 다시 재고 두 수치를 나란히 보고한다.** 속도만 보고하고 F1은 양자화 전 값을 쓰면 수치 조작이 된다.

---

## 10. 막히면

| 증상 | 먼저 볼 것 | 조치 |
|---|---|---|
| `CUDA out of memory` | 학습 중인가 평가 중인가 | [B-detector.md §10.1](../B-detector.md) 사다리 |
| 손실이 `nan` | fp16인가 | 학습률 ↓ · `bf16` 또는 fp32 · `max_grad_norm=1.0` |
| **손실은 내려가는데 F1이 0** | `labels`에서 `-100`·`O`를 뺀 개수 | 0이면 정렬 버그 → §3 |
| 100건 과적합이 안 된다 | 데이터 파이프라인 | §5. **모델을 의심하지 않는다** |
| `return_offsets_mapping` 에러 | `tok.is_fast` | fast 토크나이저로 로드 (§1) |
| `TrainingArguments` 인자 에러 | transformers 버전 | 에러 메시지의 이름으로 바꾸고 버전 고정 |
| offset이 원문과 안 맞는다 | §2.1 `sanity()` | **A에게 즉시 알린다.** 혼자 고치지 않는다 |
| `O`가 너무 많다 | 정상이다 | [B-detector.md §10.3](../B-detector.md) |
| 평가 F1이 학습보다 크게 낮다 | **인물 단위로 나눴는가** | §2.3. 글 단위로 나눴으면 문체 누수다 |
| 학습이 너무 오래 걸린다 | `max_length` · 배치 | 256/16이면 3060에서 수 시간. 하루가 넘으면 설정이 잘못됐다 |
| Kaggle 세션이 끊겼다 | 체크포인트가 남았는가 | §8. 남지 않았으면 `save_steps`를 줄인다 |

---

## 11. 완료 확인

- [ ] `sanity()`에서 offset 불일치 0건
- [ ] 왕복 테스트에서 `bad` < 10% — `near` 비율을 **파이프라인 상한으로 기록**
- [ ] 잘린 스팬 비율 측정 후 기록
- [ ] **인물 단위 분할** — 분할 결과를 시드와 함께 파일로 저장
- [ ] 100건 과적합 테스트 F1 ≥ 0.9
- [ ] 전체 학습이 끝까지 돌고 `eval_recall`이 0이 아님
- [ ] 체크포인트 재개가 실제로 동작함 (일부러 죽여서 확인)
- [ ] 등급별 정확 일치 F1 · 재현율 · 부분 일치 F1 표 완성
- [ ] `SpanDetector.detect()` 출력이 `span.schema.json`과 일치
- [ ] CPU 지연 중앙값 측정 — 하드웨어·스레드 수 기록
- [ ] 양자화했다면 **양자화 후 F1을 다시 측정**
- [ ] `models/registry.md`에 한 행 추가 (가중치는 커밋하지 않는다)
