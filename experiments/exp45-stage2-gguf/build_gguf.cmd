@echo off
rem [OLD - rejected Q5_K_M merged procedure, kept for history] 115 accounts 797/805 vs NF4 (exp45 result 3/4).
rem The app now uses dq_base.py + build_gguf_lora.cmd (Q8_0 base + LoRA f32, no merge).
rem 2/3 · 3/3 — merge_dq.py 결과(bf16 HF 폴더) -> GGUF bf16 -> Q5_K_M. llama.cpp 는 b12090 으로 고정한다.
rem   build_gguf.cmd <merged 폴더> <출력 폴더>
rem 필요한 것 (저장소 밖):
rem   LLAMA_SRC  = llama.cpp b12090 소스 (convert_hf_to_gguf.py · github.com/ggml-org/llama.cpp releases b12090 src)
rem   LLAMA_BIN  = llama-b12090-bin-win-cuda-13.4-x64 압축을 푼 폴더 (llama-quantize.exe · llama-server.exe)
rem   CONVERT_PY = convert 용 파이썬 (gguf 0.19.0 · torch · transformers 4.57 · safetensors 가 있는 별도 venv — 메인 환경에 설치하지 않는다)
rem 끝나면 certutil 로 SHA-256 을 출력한다 — src/kopl/c4_stage2/infer.py GGUF_SHA256 과 같아야 앱이 기동한다
setlocal
set PYTHONIOENCODING=utf-8
set HF_HUB_OFFLINE=1
if "%~2"=="" (echo usage: build_gguf.cmd ^<merged^> ^<outdir^> & exit /b 2)
"%CONVERT_PY%" "%LLAMA_SRC%\convert_hf_to_gguf.py" "%~1" --outtype bf16 --outfile "%~2\stage2v2-dq-bf16.gguf"
if errorlevel 1 exit /b 1
"%LLAMA_BIN%\llama-quantize.exe" "%~2\stage2v2-dq-bf16.gguf" "%~2\stage2v2-dq-Q5_K_M.gguf" Q5_K_M
if errorlevel 1 exit /b 1
certutil -hashfile "%~2\stage2v2-dq-Q5_K_M.gguf" SHA256
