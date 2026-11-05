@echo off
rem 2/2 - dq_base.py result (bf16 HF folder, no adapter) -> GGUF bf16 -> Q8_0, and v2 LoRA -> LoRA GGUF f32. llama.cpp pinned to b12090.
rem   build_gguf_lora.cmd <dq folder> <v2 adapter folder> <out folder>
rem Needs (outside the repo):
rem   LLAMA_SRC  = llama.cpp b12090 source (convert_hf_to_gguf.py, convert_lora_to_gguf.py)
rem   LLAMA_BIN  = llama-b12090-bin-win-cuda-13.4-x64 unpacked (llama-quantize.exe, llama-server.exe)
rem   CONVERT_PY = python for convert (gguf 0.19.0, torch, transformers 4.57, safetensors - separate venv)
rem Output: stage2v2-dqonly-Q8_0.gguf (STAGE2_GGUF) and stage2v2-lora-f32.gguf (STAGE2_GGUF_LORA).
rem The two SHA-256 printed at the end must equal GGUF_SHA256 / GGUF_LORA_SHA256 in src/kopl/c4_stage2/infer.py.
rem The intermediate bf16 GGUF (about 8 GB) can be deleted afterwards.
setlocal
set PYTHONIOENCODING=utf-8
set HF_HUB_OFFLINE=1
if "%~3"=="" (echo usage: build_gguf_lora.cmd ^<dq^> ^<adapter^> ^<outdir^> & exit /b 2)
"%CONVERT_PY%" "%LLAMA_SRC%\convert_hf_to_gguf.py" "%~1" --outtype bf16 --outfile "%~3\stage2v2-dqonly-bf16.gguf"
if errorlevel 1 exit /b 1
"%LLAMA_BIN%\llama-quantize.exe" "%~3\stage2v2-dqonly-bf16.gguf" "%~3\stage2v2-dqonly-Q8_0.gguf" Q8_0
if errorlevel 1 exit /b 1
rem convert_lora reads only the base config from --base: give it a folder with the config/tokenizer files only (same as measured)
if not exist "%~3\base_cfg" mkdir "%~3\base_cfg"
for %%F in (config.json generation_config.json tokenizer.json tokenizer_config.json vocab.json merges.txt) do copy /y "%~1\%%F" "%~3\base_cfg\%%F" >nul
"%CONVERT_PY%" "%LLAMA_SRC%\convert_lora_to_gguf.py" --outtype f32 --base "%~3\base_cfg" --outfile "%~3\stage2v2-lora-f32.gguf" "%~2"
if errorlevel 1 exit /b 1
certutil -hashfile "%~3\stage2v2-dqonly-Q8_0.gguf" SHA256
certutil -hashfile "%~3\stage2v2-lora-f32.gguf" SHA256
