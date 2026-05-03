@echo off
setlocal

REM Keep UTF-8 console for Chinese file names and instruction text.
chcp 65001 >nul

pushd "%~dp0"

REM ==================================================
REM Only change these 3 variables for each formal run.
REM ==================================================
set "INPUT_FILE=first.txt"
set "INSTRUCTION=我要的情节是女主角被重塑造了一个身体，过程和前面情节的抽取灵魂差不多，要有相似的情节元素和过程，要一个章节，1万字的具体内容，主角都差不多。"
set "ROUNDS=10"
set "LLM_ANALYSIS=0"

REM ---------------------------
REM Fixed defaults (usually unchanged)
REM ---------------------------
set "NOVEL_DIR=novels_input"
set "OUTPUT_DIR=novels_output"
set "MODEL=deepseek-v3-2-251201"
set "LLM_MAX_TOKENS=2200"
set "LLM_TEMPERATURE=0.4"
set "LLM_TIMEOUT_S=180"
set "CHAPTER_NUMBER=2"
set "ANALYSIS_MAX_CHUNK_CHARS=1800"

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
if "%STAMP%"=="" (
  echo [ERROR] Failed to generate timestamp.
  exit /b 1
)

for %%F in ("%INPUT_FILE%") do set "STORY_ID=story-%%~nF"

echo [INFO] Activating conda environment: novel-create
call conda activate novel-create
if errorlevel 1 (
  echo [ERROR] Failed to activate conda environment "novel-create".
  echo [HINT] Run this in Anaconda Prompt or ensure "conda" is in PATH.
  exit /b 1
)

set "CURRENT_NOVEL_DIR=%NOVEL_DIR%"
set "CURRENT_INPUT=%INPUT_FILE%"

for %%F in ("%CURRENT_INPUT%") do set "STEM=%%~nF"
set "TASK_ID=task-%STEM%"
set "OUT_TXT=%STEM%.%STAMP%.chapter.txt"
set "OUT_INITIAL_STATE=%STEM%.%STAMP%.initial.state.json"
set "OUT_STATE=%STEM%.%STAMP%.final.state.json"
set "OUT_ANALYSIS=%STEM%.%STAMP%.analysis.json"
set "OUT_TRACE=%STEM%.%STAMP%.trace.json"

echo.
echo [INFO] Internal chapter rounds: %ROUNDS%
echo [INFO] Source dir: %CURRENT_NOVEL_DIR%
echo [INFO] Source file: %CURRENT_INPUT%
echo [INFO] LLM max tokens: %LLM_MAX_TOKENS%
echo [INFO] LLM temperature: %LLM_TEMPERATURE%
echo [INFO] LLM analysis: %LLM_ANALYSIS%

set "LLM_ANALYSIS_FLAG="
if "%LLM_ANALYSIS%"=="1" set "LLM_ANALYSIS_FLAG=--llm-analysis"

python run_novel_continuation.py ^
  --mode analyze-continue ^
  --novel-dir "%CURRENT_NOVEL_DIR%" ^
  --input-file "%CURRENT_INPUT%" ^
  --instruction "%INSTRUCTION%" ^
  --task-id "%TASK_ID%" ^
  --source-type "target_continuation" ^
  %LLM_ANALYSIS_FLAG% ^
  --model "%MODEL%" ^
  --llm-max-tokens %LLM_MAX_TOKENS% ^
  --llm-temperature %LLM_TEMPERATURE% ^
  --llm-timeout-s %LLM_TIMEOUT_S% ^
  --story-id "%STORY_ID%" ^
  --chapter-number %CHAPTER_NUMBER% ^
  --chapter-rounds %ROUNDS% ^
  --chapter-min-chars 1200 ^
  --chapter-min-paragraphs 4 ^
  --chapter-min-anchors 2 ^
  --chapter-plot-progress-min-score 0.45 ^
  --completion-weight-chars 0.35 ^
  --completion-weight-structure 0.25 ^
  --completion-weight-plot 0.40 ^
  --completion-threshold 0.72 ^
  --analysis-max-chunk-chars %ANALYSIS_MAX_CHUNK_CHARS% ^
  --persist ^
  --output-dir "%OUTPUT_DIR%" ^
  --output-file "%OUT_TXT%" ^
  --analysis-file "%OUT_ANALYSIS%" ^
  --initial-state-file "%OUT_INITIAL_STATE%" ^
  --trace-file "%OUT_TRACE%" ^
  --state-file "%OUT_STATE%"

if errorlevel 1 (
  echo [ERROR] Internal chapter loop failed.
  exit /b 1
)

echo [DONE] Internal chapter loop completed.
echo [DONE] Outputs are in "%OUTPUT_DIR%".
exit /b 0
