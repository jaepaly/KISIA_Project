# 벤치마크 러너 — 1단(B) · 하류(D) · 한 줄 실행 (11/2 최종 측정용)

`run.py`(B)는 1단, `d_*.py`(D)는 2단·위험도·조치·ablation·회귀다. **`run_all.py`가 둘을 한 줄로 잇는다**
(아래 「한 줄 실행」). 하류 요약은 1단 `metrics.json`의 `extensions.downstream`에 채운다.
모델·규칙·임계값을 고르는 도구가 아니며 재학습·자동 탐색을 하지 않는다.
최종 test는 11/2(월) 확정 구성(11/1 동결 커밋)으로 한 번만 실행한다. 지금은 **train 일부로 동작만 확인**한다.

## 입력·출력

- 체크포인트, `--rules on/off`, `--threshold`(기본 0.7), CPU 스레드 수를 받는다.
  기본 데이터는 train 검수 20편이다. `--limit`은 train 검증에서만 허용한다.
- test는 `--split test --final-test-confirm`으로 명시적으로 확인해야 한다.
  고정 ID 255개와 `test.jsonl` SHA-256 `9662a167…`을 검사하고,
  기존 평가기의 IAA 제외·blind 우선/clue·검수/noise 정책을 그대로 써서 239편을 평가한다.
- 출력은 **새로운 `experiments/**/runs/` 폴더**에 `metrics.json`과 `predictions.jsonl`이다.
  기존 폴더는 덮어쓰지 않는다. 예측 파일에는 post_id·candidates를 쓰며 탐지 없는 글도 남긴다.
- 체크포인트 SHA-256(가중치 · 토크나이저 · config), 학습 BIO 지문(체크포인트에 저장된 경우), 실제 골드 파일 지문,
  규칙·속성 판정·앱 병합·평가 코드 커밋과 파일 해시, 측정일·환경을 기록한다.
- 체크포인트에 학습 BIO 지문(`run_config.data_sha256`)이 있으면 `--bio-data` 와 대조해 다르면 중단한다
  (train smoke 에서도 대조하므로 11/2 전에 미리 확인된다). 지문이 없는 v1 은 `verified: false` 와 한계 문장을 남긴다.
  예전 결과와 골드 level 관례가 달라도 구분할 수 있다.

## 지표의 뜻

| metrics.json 항목 | 의미 |
|---|---|
| `c1.boundary_type.partial` / `exact` | 기존 공식 경계·유형 채점. partial은 type 일치 + IoU ≥ 0.5 탐욕 1:1, exact는 참고치 |
| `c1.proxy.partial_by_level` / `exact_by_level` | 명시·암묵·추론의 **골드 등급**별 TP·FN·R, 전체 정밀도 공유 P와 proxy F1. partial에는 #276 보수적 참고 F1도 포함 |
| `c1.resolved_level.partial` / `exact` | 경계·유형에 더해 **resolve()가 판정한 level도 일치**해야 TP인 end-to-end P/R/F1, 전체와 등급별. 독립 level 분류 정확도가 아니며 subject는 매칭 조건이 아님 |
| `c1.implicit_iaa` | 2차 IAA의 공개 반올림값 44.4% 대비 proxy·등급 판정 포함 F1의 참고 비율/백분율. 다른 표본·정의라 사람 대비 성능 확증이 아님 |
| `c1.bootstrap_ci` | 명시 proxy F1 · 명시 재현율 · 정밀도 · 재현율 · F1 · 등급 판정 포함 명시 F1 · 등급 판정 포함 F1 의 **95% 신뢰구간**. 글 단위 복원추출 2,000회 · 시드 20261102(측정 전 고정 · PM 결정 10/25) · 백분위 방식. 점추정은 전체 표본 값이고, 글별 합이 위 공식 채점과 다르면 중단한다. 명시 골드가 없으면 공식 채점처럼 null 이고, 뽑은 표본에 명시 골드가 없던 회차는 빼고 `undefined_resamples` 에 수를 적는다. 같은 인물의 글끼리는 독립이 아니라 인물 단위로 뽑으면 구간이 더 넓어진다 — 이 test 표본의 표집 오차로만 읽는다 |
| `c1.fp_breakdown.by_cause` | 부분 일치에서 짝 없는 예측(FP)을 기계적으로 다섯 갈래로 나눈 것. 합 = 전체 FP. `boundary_low_iou` 같은 유형 골드와 겹치나 IoU < 0.5 · `duplicate_of_matched` 그 골드를 다른 예측이 이미 가져감 · `type_confusion` 다른 유형 골드와만 겹침(`type_confusion_pairs` 에 골드→예측 유형) · `unannotated_repeat` 겹치는 골드는 없으나 같은 글에 같은 유형 · 같은 글자의 골드가 있음 · `no_overlap` 나머지. 「골드 관례 차이인가」는 사람 판단이라 가르지 않는다 |
| `additional_detection` | exp01 세 도구 합집합의 미탐 중 현재 모델+선택 규칙이 회수한 수/비율. 기존 도구는 type 불문·1:1 제한 없음, 모델은 공식 type 일치·탐욕 1:1 |
| `cpu_latency.model_only` / `app_full` | #301 모델 detect(계약 검증·임시 속성 포함)와 앱 detect(선택 규칙 병합·resolve 포함)를 **같은 표본**으로 별도 측정 |

해당 등급의 골드가 없으면 R/F1은 null이며, 표본이 있는 등급의 TP가 0이면 F1은 0이다.
지연은 #301의 길이순 구간 중앙 표본 알고리즘을 재사용한다. 최종 test에서는 같은 20편,
글마다 워밍업 5회·측정 50회, 1편씩 호출한다. 분포는 **글별 중앙값의 중앙값·p95(nearest-rank)·최대**다.
모델 로딩은 제외하고 창 배치 수를 따로 적는다. train smoke에서 줄인 반복값은 최종 지연이 아니다.

## 오늘 실행할 검증 — test 아님

저장소 루트의 PowerShell에서 실행한다. torch·transformers와 로컬 체크포인트,
Presidio·spaCy·`ko_core_news_sm`이 필요하다. 기존 도구가 없거나 Presidio가
대체 엔진으로 폴백하면 중단한다. 가중치 다운로드·LLM 호출은 하지 않는다.

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python experiments/bench/run.py --checkpoint-dir experiments/exp06-finetune/runs/variant_base_20261008/checkpoint-epoch-10 --split train --limit 4 --rules on --threshold 0.7 --threads 4 --latency-samples 2 --warmup 1 --repeats 2 --output-dir experiments/bench/runs/smoke_v2_rules_20261014
```

규칙 끔 ablation은 위 명령의 `--rules off`와 **다른 출력 경로**를 사용한다.
개발 환경에 기존 도구가 없으면 `--skip-baselines`, 측정 없이 채점 조립만 보면
`--skip-latency`를 쓸 수 있지만 `status: not_measured`로 남는다. test에서는 skip을 금지한다.
train 검수 부분집합 점수는 학습과 겹치므로 일반화 성능으로 보고하지 않는다.

모델 없는 단위 테스트:

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python -m unittest discover -s experiments/bench -p test_run.py -v
```

## 11/2에만 실행할 1단 단독 명령 (참고)

아래는 1단 전체 지표만 모으는 명령이다. **11/2 에는 이 명령 대신 아래 「11/2 측정 체크리스트」의
`run_all.py --final` 한 줄을 친다** — 1단 옵션은 이 명령과 같고 `--split` · `--final-test-confirm` · `--output-dir`만
`run_all.py`가 넣는다. 지금은 실행하지 않는다.

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python experiments/bench/run.py --checkpoint-dir experiments/exp06-finetune/runs/variant_base_20261008/checkpoint-epoch-10 --bio-data experiments/exp06-finetune/runs/bio_variant_base_20261008/train.jsonl --split test --final-test-confirm --rules on --threshold 0.7 --threads 4 --output-dir experiments/bench/runs/final_v2_20261102
```

기존 `measure_additional_rate.py` CLI는 W7 v1 저장 결과 재현용으로 유지한다.
새 러너는 그 모듈의 `run_baselines`와 모델 버전 제한 없는 `score_additional_rate` 경로를
사용하므로 v2·규칙 결합 예측도 같은 미탐 정의로 평가한다.

## 한 줄 실행 — `run_all.py` (1단 → 2단 → 위험도·조치 → ablation → 회귀)

`run_all.py`는 B의 `run.py`를 **고치지 않고 별도 프로세스로 그대로** 부른다. 지연 측정에 하류 모듈이 섞이지 않게 하고,
규칙 켬/끔이 프로세스 단위로 정해지기 때문이다. 순서는 이렇다.

1. **1단** — `run.py`를 부른다. `--` 뒤에 붙인 옵션은 `run.py`에 그대로 넘긴다. 출력은 `<output-dir>/stage1/`
2. **변환** — 1단 `predictions.jsonl`의 `{"post_id", "candidates"}`를 하류 입력 `{"post_id", "spans"}`로 옮긴다.
   바꾸는 것은 키 이름뿐이다. 형식이 다르거나 post_id가 중복이면 멈춘다. 출력은 `<output-dir>/downstream_preds.jsonl`
3. **하류** — `d_downstream.run_downstream`이 2단 → 위험도·조치 → ablation(②·③) → (`--final`이면) 회귀 exp09·10·11 순서로 돈다.
   출력은 `<output-dir>/downstream/metrics_downstream.json`. 단계마다 `status`와 `seconds`가 붙는다
4. **요약** — `<output-dir>/bench_summary.json`에 단계별 status·걸린 시간·1단 명령을 남긴다. 1단 `metrics.json`의 `extensions.downstream`에도 같은 요약이 들어간다

| 옵션 | 뜻 |
|---|---|
| `--output-dir` | experiments 아래 `runs/`가 들어간 **새** 경로. 이미 있으면 멈춘다 (run.py와 같은 규칙) |
| `--final` | 11/2 최종 측정. 1단에 `--split test --final-test-confirm`, 하류에 `--final`(test 허용 + 회귀)을 함께 켠다 |
| `--stage2-mode rules·model·both` | `both`는 2단 규칙 경로를 먼저 돌리고(`downstream_rules/stage2`) 모델 경로 하류와 비교한다. ablation ④ 일치율이 이 한 줄로 나온다. 위험도·조치·ablation·회귀는 한 번만 돈다 |
| `--ablation` | 기본은 ②·③ 둘 다. `--ablation`만 쓰고 이름을 비우면 끈다 |
| `--adapter` | 2단 어댑터 폴더. 기본은 `STAGE2_ADAPTER_DIR`, 그다음 앱 기본 `exp08 results/adapter_v2` |
| `--preds` / `--stage1-dir` | 1단을 건너뛰고 하류만 돈다. `--preds`는 spans 형식 파일(예: exp24 dev)이고 `--final`과 같이 쓸 수 없다. `--stage1-dir`은 이미 돈 run.py 출력 폴더다. `--final`과 같이 쓰면 최종 test 출력만 받는다(11/2 하류 재실행용) |
| `-- <run.py 옵션>` | `--checkpoint-dir` · `--bio-data` · `--rules` · `--threshold` · `--threads` · `--limit` · 지연 표본 옵션 등 |

**test 보호** — `--split` · `--final-test-confirm` · `--output-dir`은 `run_all.py`가 정한다. 1단 옵션에 직접 넣으면 멈춘다
(`--spl`, `--final-t` 같은 argparse 줄임도 막는다). `--final`이 없으면 1단은 언제나 `--split train`이다.
하류도 `--final`이 없으면 test 글(`splits/test_post_ids.json`의 `["post_ids"]` 255개)이 하나라도 섞이는 순간 멈춘다.
1단이 실패하면(종료 코드 ≠ 0) 하류는 돌지 않는다. 어느 단계든 failed면 종료 코드는 1이다.

규칙 끔 ablation ①은 1단 옵션만 `--rules off`로 바꾸고 **다른 `--output-dir`** 로 한 번 더 친다.

### 개발 확인 결과 (10/19 · D PC · test 아님)

PC 사양: D 데스크톱 `DESKTOP-828COMG` · AMD Zen3 CPU 4스레드 · RTX 3060. 이 PC에는 **1단 v2 체크포인트(`d7dc7b06…`)와 2단 v2 어댑터 가중치가 없다.**
그래서 두 가지로 나눠 확인했다. 1단이 포함된 한 줄 경로는 등록 v1 체크포인트(`3c2d9867…`)로 돌렸고,
v2 규모 확인은 exp24에 저장된 v2 dev 예측(2,281편, [#350](../../../../pull/350))을 하류에만 넣어 돌렸다. 2단은 둘 다 규칙 모드다.

| 실행 | 1단 | 2단 | 위험도·조치 | ablation ② | ablation ③ | 전체 |
|---|---|---|---|---|---|---|
| ① 한 줄 전체 · train 검수 20편(10명) · v1 · 규칙 켬 · 지연 표본 4편×3회 | OK 50.2 s (로딩·기준 도구·지연 포함) | OK 1.8 s | OK 1.2 s | OK 0.2 s | OK 0.2 s | **54.1 s** |
| ② 하류만 · exp24 v2 dev 2,281편(94명) | — | OK 19.0 s (사용자당 중앙값 0.15 s) | OK 41.3 s | OK 1.5 s | OK 1.1 s | **63.0 s** |

```powershell
# ① 1단 포함 한 줄 (train smoke · 이 PC 는 v1 체크포인트만 있다)
$env:PYTHONIOENCODING="utf-8"; python experiments/bench/run_all.py --output-dir experiments/bench/runs/dev_smoke_v1_rules_20261019 --stage2-mode rules -- --checkpoint-dir C:/Users/dor12/kisia_models/runs/v1_lr5e-5/checkpoint-epoch-10 --limit 20 --rules on --threshold 0.7 --threads 4 --latency-samples 4 --warmup 1 --repeats 3
# ② 하류만 (v2 dev 예측)
$env:PYTHONIOENCODING="utf-8"; python experiments/bench/run_all.py --output-dir experiments/bench/runs/dev_exp24_v2_rules_20261019 --stage2-mode rules --preds experiments/exp24-cpu-accel/results/preds_dev_fp32.jsonl
```

①의 점수와 지연은 train 일부이고 v1이라서 **성능 숫자로 쓰지 않는다**. 이 실행은 연결이 끝까지 도는지만 확인한 것이다.
아직 확인하지 못한 것:
- **2단 모델 모드**(`model`·`both`)와 `--final` 회귀(exp09는 GPU 로컬 생성)는 이 PC에 어댑터가 없어 돌리지 못했다. 단위 테스트(`test_run_all.py`)로 연결만 확인했으니 **어댑터가 있는 PC에서 dev로 한 번 더 확인해야 한다**
- 1단 v2 체크포인트로 도는 한 줄 경로도 v2가 있는 PC에서 확인해야 한다

모델 없는 단위 테스트(run_all 포함):

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python -m pytest -q --import-mode=importlib experiments/bench
```

## 11/2 측정 체크리스트

> 11/2(월)에 test를 **한 번만** 잰다. 그 전에는 test로 아무것도 돌리지 않는다. 동결 일정은 [README](../../README.md) 「앞으로의 일정」을 따른다 (DEC-015).

**누가 · 어느 PC**
- 담당은 **B(1단)와 D(하류)** 다. 같은 자리에서 같이 확인한다
- PC는 **한 대에서 한 줄로** 돌린다. 추천은 **B 데스크톱**이다. 1단 v2 체크포인트가 그 PC에 있고, CPU(Ryzen 5 9600X)가 #301 지연을 잰 CPU와 같으며, GPU(RTX 5070)가 있다. 2단 v2 어댑터는 D가 보관본을 비공개로 전달하고 SHA를 맞춘다. → **PM 확정 필요** (다른 PC로 하면 지연 숫자를 #301과 바로 비교할 수 없다)

**동결 커밋**
- 일 11/1 최종 동결 커밋. 해시는 동결 때 이 칸에 적는다: `⟦11/1 동결 커밋⟧`
- 측정 PC에서 `git status`가 깨끗해야 한다(`git status --porcelain` 출력 없음). d_stage2 지문은 고친 파일이 있으면 `+dirty`를 붙인다

**모델 파일과 SHA-256** (측정 전에 `certutil -hashfile <파일> SHA256` 또는 `sha256sum`으로 확인)

| 무엇 | 경로 | SHA-256 | 근거 |
|---|---|---|---|
| 1단 v2 가중치 | `experiments/exp06-finetune/runs/variant_base_20261008/checkpoint-epoch-10/model.safetensors` | `d7dc7b06d9557c13152c8ad5e91f51f56e154f1e8adc8d2b3ab49f525dfa06be` | [models/registry.md](../../models/registry.md) 1단 koelectra-v2 |
| 1단 학습 BIO (`--bio-data`) | `experiments/exp06-finetune/runs/bio_variant_base_20261008/train.jsonl` | `fcdd0da11e3cec5f01447c8cf864f60d0af84659e3e7bd35e003747e49199e6f` | 같은 곳. run.py가 체크포인트의 `run_config.data_sha256`과 대조한다 |
| 2단 v2 어댑터 | `experiments/exp08-stage2-sft/results/adapter_v2/adapter_model.safetensors` | `c045d35324f0ed6c90a2b4e84106a02eb6750e38c0f5c1b73be107ba4d882c7e` (10/15 재학습본) | registry 2단 qwen3-4b-qlora-v2 |
| 2단 v2 어댑터 설정 | `…/adapter_v2/adapter_config.json` | `e534cc2f2a6dec9de5bfe5d2387afe74a9a8008288d30e43653804488e9495d1` | 같은 곳 |
| test 글 | `data/corpus/v0/splits/test.jsonl` | `9662a167f530f47318da2bd37a8401988ee74555393d6cd377fa84dfe8a886ad` | run.py가 검사한다 · split_meta.json |

⚠️ exp09 회귀는 저장된 결과가 있으면 그 meta의 어댑터 SHA와 비교한다. 기록된 exp09 결과는 10/12 학습본(`94ada34d…`)으로 잰 것이라
10/15 재학습본(`c045d353…`)으로 돌리면 **`failed`(덮어쓰지 않음)가 나온다** (`data/qwen_cfg_v2_meta.json`의 `adapter_sha256`이 `94ada34d…`, 10/19 확인). 11/1 전에 D가 (가) 10/15 본으로 exp09를 다시 잴지 (나) 회귀에서 exp09는 저장 결과(10/12 본)로 두고 한계로 적을지 정해 이 칸에 적는다 ([ABLATION.md](ABLATION.md) 「최종 측정 회귀」).

**실행 명령 (저장소 루트 PowerShell · 그대로 친다)**

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python experiments/bench/run_all.py --final --output-dir experiments/bench/runs/final_v2_20261102 --stage2-mode both -- --checkpoint-dir experiments/exp06-finetune/runs/variant_base_20261008/checkpoint-epoch-10 --bio-data experiments/exp06-finetune/runs/bio_variant_base_20261008/train.jsonl --rules on --threshold 0.7 --threads 4
```

ablation ①(규칙 끔)은 출력 폴더를 다르게 주고 하류 없이 1단만 비교해도 된다:

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="src;experiments/exp06-finetune"; python experiments/bench/run.py --checkpoint-dir experiments/exp06-finetune/runs/variant_base_20261008/checkpoint-epoch-10 --bio-data experiments/exp06-finetune/runs/bio_variant_base_20261008/train.jsonl --split test --final-test-confirm --rules off --threshold 0.7 --threads 4 --output-dir experiments/bench/runs/final_v2_rulesoff_20261102
```

**결과 파일 위치** (`experiments/**/runs/`는 gitignore라 저장소에 올라가지 않는다. 측정 PC 로컬에 남기고 D에게 폴더째 넘긴다)
- `experiments/bench/runs/final_v2_20261102/stage1/metrics.json` — 1단 F1(proxy·등급 판정 포함) · 추가 탐지율 · CPU 지연 · `extensions.downstream`
- `…/stage1/predictions.jsonl` · `…/downstream_preds.jsonl`
- `…/downstream/metrics_downstream.json` — 2단(모델) · 위험도·조치 · ablation ②③ · ④ 일치율(`stage2_compare`) · 회귀 exp09·10·11
- `…/downstream_rules/stage2/` — ④의 규칙 쪽 · `…/bench_summary.json` — 단계별 status·걸린 시간

**CPU 지연 20편 절차** (위 명령 안에서 같이 돈다 · 따로 치지 않는다)
- run.py가 #301과 같은 길이순 구간 중앙 표본 알고리즘으로 test 20편을 고른다. 글마다 워밍업 5회·측정 50회, 1편씩 호출, 4스레드
- 모델 단독(`cpu_latency.model_only`)과 앱 경로 전체(`app_full`)를 같은 20편으로 따로 잰다. 모델 로딩은 빼고 따로 적는다
- **지연을 볼 때는 그 20편의 정답·오류·F1을 열지 않는다.** `cpu_latency`만 본다
- 측정 중에는 다른 무거운 프로그램(브라우저 영상·학습·Ollama)을 끈다. 전원 설정은 「고성능」으로 둔다

**실패하면**
- **멈춘 지점을 `bench_summary.json`의 `stages`와 터미널 마지막 줄로 확인한다.** 결과 폴더는 지우지 않는다(증거). 다시 칠 때는 **새 `--output-dir`** 를 쓴다(예: `final_v2_20261102_r2`). 같은 폴더는 덮어쓰지 않게 막혀 있다
- 1단 실패(SHA·BIO 대조·test 지문·도구 폴백 등) → 원인을 고친다. 모델·규칙·임계값은 바꾸지 않는다. 파일이나 환경 문제면 고치고 새 폴더로 다시 친다. 코드 수정이 필요하면 「치명적 버그 수정만」 규칙에 따라 PR로 고치고, 그 지표를 다시 잰다
- 1단은 OK이고 하류만 실패 → 1단을 다시 돌리지 않는다. 원인을 고친 뒤 하류만 다시 돈다: `python experiments/bench/run_all.py --final --output-dir experiments/bench/runs/final_v2_20261102_ds2 --stage2-mode both --stage1-dir experiments/bench/runs/final_v2_20261102/stage1` (`--final --stage1-dir`은 run.py 최종 test 출력만 받는다)
- 2단 모델 로드 실패 → 규칙으로 바꿔 재지 않는다(d_stage2가 멈춘다). 어댑터 경로·SHA를 확인한다
- test를 본 뒤에는 **어떤 경우에도 고르기를 다시 하지 않는다.** 결과가 나쁘면 한계로 적는다

관련: [README B 2번 · D 5번 · 6번](../../README.md), [#276](../../../../issues/276),
[#301](../../../../pull/301), [#322](../../../../issues/322).
