#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HOME="${HF_HOME:-$ROOT_DIR/cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$ROOT_DIR/cache/huggingface}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-$ROOT_DIR/cache/modelscope}"
export TMPDIR="${TMPDIR:-$ROOT_DIR/cache/tmp}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$ROOT_DIR/cache/pip}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-4B}"
export RERANK_MODEL="${RERANK_MODEL:-Qwen/Qwen3-Reranker-4B}"

mkdir -p "$HF_HOME" "$TRANSFORMERS_CACHE" "$MODELSCOPE_CACHE" "$TMPDIR" "$PIP_CACHE_DIR"
exec /home/data/nas_hdd/jinglong/waf/conda-envs/novel_embedding_waf/bin/python download_models.py
