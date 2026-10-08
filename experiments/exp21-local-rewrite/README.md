# exp21 — 로컬 바꿔 쓰기 (직업·장소·집 근처 단서)

**무엇을 왜 재는가** — 규칙 바꿔 쓰기 엔진(`src/kopl/c4_stage2/rewrite.py`)은 확실한 후보만 낸다. 합성 골드(test 제외) 본인 단서 기준으로
명시 53% · 암시 29% · 추론 16% 에만 후보가 있고, **직업은 370개 중 2개 · 집 근처는 191개 중 0개**다. 실제 글 내부 시험(10/8)에서 외부 LLM 검토자는
수정안을 25개 냈는데 우리는 0개(오탐 지명 후보 5개뿐)였다. 글을 밖으로 보내지 않고, 이미 GPU 에 올라간 2단 모델(Qwen3-4B)로 후보를 만들 수 있나.

## 방식

- 바꿀 말 = 규칙 엔진이 후보를 못 낸 **본인 단서**. 글 전문 + 바꿀 말 목록(핵심어 · 유형 · 앞뒤 문맥)을 주고 JSON 으로 받는다 (`rewrite_llm.py`)
- 모델은 **조사를 뗀 핵심어만** 바꾼다 → 조사는 `josa.replace` 가 받침에 맞춰 다시 붙인다
- 거름: 원래 핵심어를 그대로 품음(「탄천 → 탄천 근처」) · 앞뒤 말과 겹침 · 조사를 못 맞춤 · **바꾼 글을 1단에 다시 넣으면 같은 자리 · 같은 유형 단서가 또 잡힘(잔존)**
- 채점: Codex(gpt-6.1-sol)가 후보마다 natural · meaning · less · wrong 을 0/1 (`judge_prompt.txt`). **good** = 앞 셋 1 · wrong 0

## 결과

| 버전 | 모델 | 평가 | 후보 | good | wrong |
|---|---|---|---|---|---|
| v0 | Qwen3-4B 기본 · 구간 통째 | 15편 40단서 | 28 | (눈으로) 절반 · 조사 빠짐 · 앞뒤 겹침 | — |
| v1 | Qwen3-4B 기본 · 핵심어 + 거름 | **40편 102단서** (`results/v1_eval40*`) | 49 | **21** (후보의 43% · 전체의 21%) | **16** (33%) |
| **v2 (B)** | + 바꿔 쓰기 어댑터 (교사 GPT 증류 · 2 epoch) | 같은 40편 (`results/v2_eval40*`) | **73** | **46** (후보의 63% · 전체의 45%) | **11** (15%) |

v2 — 증류로 후보 49 → 73, good 21 → 46, wrong 33% → 15%. 직업 good 2/4 → **7/11**, 장소 9/19 → 21/30. 학습: 교사 413편 → 정제 후 train 372 · dev 41 (1024토큰 넘는 63 · 7편 버림) · dev loss 1.977 → 0.402 · VRAM 5.26GB · 78업데이트. **채택 기준(good ≥ 70% · wrong ≤ 5%)에는 아직 못 미친다.** 남은 실패는 너무 막연한 말(「사람」「물건」「시설」「기간」) 9건과 다른 종류로 바꾸기(「오피스텔 → 아파트」 「유모차 → 차」 「하원 → 일상생활」 「독서실 → 공공기관」).

v1 판정: **사용자에게 보여 줄 수준이 아니다.** 틀린 정보가 후보의 1/3 — 「야자 → 유리나무」 「터미널 → 버스 정류소」 「오피스텔 → 아파트」
「영통구청 → 지방청」 「하원을 → 엄마를」. 받아들이면 글의 사실이 바뀐다. 4B 기본 모델은 생활 어휘(야자·하원·선과장)를 모르고 상위어와 다른 말을 가르지 못한다.
더 큰 모델은 데모 PC(RTX 3060 **8GB**, 2단 모델 상주)에 못 올린다.

## (B) 증류 — `make_teacher.py` → `train.py` → `run.py --adapter`

```bash
export PYTHONIOENCODING=utf-8 PYTHONPATH=src
# 1. 교사 데이터 — Codex CLI(GPT) · 6편씩 · 캐시로 이어 하기
python experiments/exp21-local-rewrite/make_teacher.py --n-posts 413 --cache <캐시>
python experiments/exp21-local-rewrite/make_teacher.py --build --cache <캐시>     # → data/train.jsonl · dev.jsonl · stats.json
# 2. 학습 — exp08 과 같은 QLoRA (r16 · NF4) · 어댑터는 커밋하지 않는다
python experiments/exp21-local-rewrite/train.py --epochs 2 --max-len 1024        # 끊기면 같은 인자 + --resume
# 3. 평가 — v1 과 같은 40편 (seed 7)
python experiments/exp21-local-rewrite/run.py --n-posts 40 --seed 7 --adapter experiments/exp21-local-rewrite/results/rewrite_adapter --out <결과>
```

- 글: 합성 골드에서 **test 글과 평가 인물 전체**(`eval_post_ids.json` 의 글을 가진 인물)를 뺀 413편 · 48명 · 단서 625개
- 교사는 GPT — Claude 계열은 교사 라벨(스팬)과 순환, Qwen 은 학습 대상 자신이라 쓰지 않는다 (`c5_corpus.llm.BLOCKED_GENERATION` 과 같은 이유)
- 교사 답도 실행과 같은 거름 + 1단 재탐지로 정제하고, 걸린 것은 **null 로 가르친다** (「못 바꾸면 안 낸다」)
- 실행 때는 2단 어댑터(default) 옆에 `rewrite` 어댑터를 얹고 호출 동안만 바꿔 끼운다 — GPU 메모리를 더 쓰지 않는다

## 채택 기준 (앱에 넣는 조건)

같은 40편에서 **good ≥ 후보의 70% · wrong ≤ 5%**. 못 넘으면 생성은 접고 유형별 안내 문구로 간다.
