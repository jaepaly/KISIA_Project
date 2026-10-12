# exp17e-job-dev: 1단 JOB 오탐 개선의 **개발용** 평가셋 — 후보를 고르는 데 쓴다

판정은 [exp17d](../exp17d-job-eval/README.md) 에서 한 번만 한다. 이 셋은 그 전에 후보를 고르는 데 쓰고, **오답을 열어 봐도 된다**.

## 왜 따로 만드나

- README W9 D 4번은 「개발용 평가(내부 eval · exp17)로 고르고 판정은 새 셋에서 한 번」이다
- B 의 내부 eval(JOB 맞음 5 · 오탐 9 · 놓침 8 · #322)은 학습 기록(`trainer_state.json`)이 B 데스크톱에만 있어 이 PC 에서 다시 만들 수 없다 (서버 체크포인트 폴더에도 없다 · 10/12 확인)
- exp17 에는 JOB 함정이 없다 — 기준선 v2 + 규칙의 심지 않은 JOB 예측이 2개뿐이다 (「직장 생활을 하는」 · 「주민이」의 「이」)
- exp17b · exp17c 는 판정에 이미 썼다 — 고르기에 다시 쓰지 않는다

## 무엇

exp17d 와 **같은 설계 · 다른 표현** — 60편 (본인 직업 20 · 남의 직함 17 · 직업 비슷한 일상 23) · seed 20261014 · post_id `P17E_`. 표현은 `specs.py` — exp17 · 17b · 17c · 17d 심은 표현 · 함정 · AUG1 정답 스팬과 부분 문자열로도 겹치지 않는다 (기존 표현 중 두 글자 이하는 비교에서 뺐다).

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=src python experiments/exp17e-job-dev/specs.py
PYTHONIOENCODING=utf-8 PYTHONPATH=src python -u experiments/exp17e-job-dev/generate.py --env .env
python experiments/exp17-planted-eval/score.py --data experiments/exp17e-job-dev/data/posts.jsonl <예측.jsonl>
```

## 한계

- exp17d 와 설계가 같아 「같은 종류의 오탐」만 본다. 실제 글의 JOB 오탐 전체를 대표하지 않는다
