#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HOME="${HF_HOME:-$ROOT_DIR/cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$ROOT_DIR/cache/huggingface}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-$ROOT_DIR/cache/modelscope}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-4B}"
export RERANK_MODEL="${RERANK_MODEL:-Qwen/Qwen3-Reranker-4B}"

CONDA_ENV_PATH="${CONDA_ENV_PATH:-/home/data/nas_hdd/jinglong/waf/conda-envs/novel_embedding_waf}"
exec "$CONDA_ENV_PATH/bin/uvicorn" app:app --host "${HOST:-0.0.0.0}" --port "${PORT:-18080}"
