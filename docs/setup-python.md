# Python 환경 세팅

> 이 문서가 정하는 것: **Python 버전 · torch CUDA 빌드 · venv 위치.**
> 라이브러리 버전은 [`requirements.txt`](../requirements.txt)가 소유한다.
>
> 아래 조합은 **RTX 3060(sm_86) + CUDA 12.8에서 실제로 검증했다** (2026-08-24). 추측이 아니다.

---

## 0. 먼저 — 이 문서가 왜 생겼나

W2에 B와 D의 환경을 맞춰보다 **세 군데가 이미 갈려 있었다.**

| | B 최진필 | D 박재현 (당시) |
|---|---|---|
| Python | 3.11.9 | **3.10.9** |
| torch | 2.11.0+**cu128** | 2.12.1+**cu130** |
| transformers | 5.15.1 | 5.12.1 |

명세가 없으니 각자 최신을 깔았고, 그 결과가 위다. 이대로 W7 「1단 F1 확정」에 가면 **한 사람이 낸 수치를 다른 사람이 재현하지 못한다.** [RULES-DO-NOT #9](RULES-DO-NOT.md)가 요구하는 «측정일 · 데이터 버전 · 모델 버전»에 **라이브러리 버전이 빠져 있던 것**도 같은 구멍이다.

---

## 1. Python 3.11

**3.11이 아니면 설치가 통째로 실패한다.** `scikit-learn 1.9.0`이 `Requires-Python >=3.11`이라, 3.10에서는 pip가 의존성 해결에 실패하고 **아무것도 깔지 않는다**(부분 설치가 아니라 전량 롤백이다).

```bash
python -V     # Python 3.11.x 여야 한다
```

3.10 이하라면 3.11을 설치한 뒤 진행한다. 패치 버전(3.11.9 / 3.11.15 …)은 달라도 된다 — 휠 호환성은 `cp311`로 묶인다.

---

## 2. venv — **저장소 안에 만들지 않는다**

```bash
python -m venv ~/venvs/kisia          # 저장소 밖
# Windows:  python -m venv C:\Users\<본인>\venvs\kisia
```

`.venv/`는 [`.gitignore`](../.gitignore)로 git에서 빠지지만, **클라우드 동기화 폴더(OneDrive·Google Drive·Dropbox)는 그걸 모른다.** 저장소가 그런 폴더 안에 있으면 —

- site-packages 수만 개 파일과 수 GB를 동기화가 계속 훑는다
- 설치 중 동기화가 파일을 잡으면 설치가 깨진다
- `.git` 내부 파일이 동기화되다 손상되는 사례도 알려져 있다

**저장소 자체를 동기화 폴더 밖에 두는 것이 더 낫다.**

---

## 3. torch — 별도 인덱스에서 먼저

```bash
pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
```

**cu128로 고정한 근거**

| GPU | 아키텍처 | 하한 |
|---|---|---|
| B 최진필 · RTX 5070 12GB | Blackwell `sm_120` | **CUDA 12.8 미만은 아예 동작하지 않는다** |
| D 박재현 · RTX 3060 8GB | Ampere `sm_86` | 12.8 정상 동작 확인 |

즉 cu128이 **두 GPU를 모두 커버하는 유일한 하한선**이다. GPU가 없거나 CPU만 쓰면 `--index-url https://download.pytorch.org/whl/cpu`.

---

## 4. 나머지

```bash
pip install -r requirements.txt
```

---

## 5. 확인

```bash
python -c "import torch, transformers, peft, bitsandbytes; \
print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

GPU 담당(B·D)은 4bit 커널까지 확인한다. **이게 통과해야 QLoRA가 성립한다.**

```python
import torch, bitsandbytes as bnb
q = bnb.nn.Linear4bit(1024, 1024, bias=False,
                      compute_dtype=torch.bfloat16, quant_type="nf4").cuda()
q.weight = bnb.nn.Params4bit(torch.randn(1024, 1024), requires_grad=False,
                             quant_type="nf4").cuda()
print(q(torch.randn(4, 1024, dtype=torch.bfloat16, device="cuda")).shape)

p = torch.nn.Parameter(torch.randn(256, 256, device="cuda"))
opt = bnb.optim.PagedAdamW8bit([p], lr=1e-4)
p.sum().backward(); opt.step()
print("PagedAdamW8bit OK")
```

**D 검증 결과 (2026-08-24 · RTX 3060 8GB · cu128 · bnb 0.50.1)**

| 항목 | 결과 |
|---|---|
| 4bit NF4 forward | OK — `(4,1024)` bfloat16 |
| 가중치 압축비 | **0.250** (fp16 대비 정확히 1/4) |
| PagedAdamW8bit step | OK |

> ⚠️ **B의 RTX 5070(sm_120)에서는 아직 확인하지 않았다.** Blackwell은 3060보다 새 아키텍처라 bitsandbytes 커널 지원이 늦게 붙는 편이다. 1단은 full fine-tuning이라 당장 필요하지 않지만, W6에 2단 학습 잡을 B의 12GB로 넘길 가능성을 열어두려면 미리 재둘 값이 있다.

---

## 6. 수치를 낼 때 함께 적는다

[RULES-DO-NOT #9](RULES-DO-NOT.md)의 «측정일 · 데이터 버전 · 모델 버전»에 **환경**을 더한다. [실험 템플릿](../experiments/_template/README.md)의 「설정」 표에 아래 줄을 채운다.

```
Python 3.11.x · torch 2.11.0+cu128 · transformers 5.15.1
peft 0.20.0 · bitsandbytes 0.50.1 · <GPU 모델> <VRAM>
```

같은 수치가 두 사람 기계에서 다르게 나오면, 이 줄이 있어야 어디서 갈렸는지 찾는다.
