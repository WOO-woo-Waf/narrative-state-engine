from __future__ import annotations

import json
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
MODEL_DIR = ROOT_DIR / "models"
MODEL_PATHS = ROOT_DIR / "model_paths.json"


def main() -> None:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B")
    os.environ.setdefault("RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")
    embedding_model = os.environ["EMBEDDING_MODEL"]
    rerank_model = os.environ["RERANK_MODEL"]
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    try:
        from modelscope import snapshot_download

        paths[embedding_model] = snapshot_download(
            embedding_model,
            cache_dir=str(MODEL_DIR),
        )
        paths[rerank_model] = snapshot_download(
            rerank_model,
            cache_dir=str(MODEL_DIR),
        )
    except Exception:
        from huggingface_hub import snapshot_download

        paths[embedding_model] = snapshot_download(
            repo_id=embedding_model,
            cache_dir=str(MODEL_DIR),
        )
        paths[rerank_model] = snapshot_download(
            repo_id=rerank_model,
            cache_dir=str(MODEL_DIR),
        )
    MODEL_PATHS.write_text(json.dumps(paths, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"downloaded: {embedding_model}")
    print(f"downloaded: {rerank_model}")


if __name__ == "__main__":
    main()
