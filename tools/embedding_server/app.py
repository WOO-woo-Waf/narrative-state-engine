from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Union

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B")
DEFAULT_RERANK_MODEL = os.getenv("RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")
ROOT_DIR = Path(__file__).resolve().parent
MODEL_PATHS = ROOT_DIR / "model_paths.json"

app = FastAPI(title="Novel Embedding Service", version="0.1.0")


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = DEFAULT_EMBEDDING_MODEL
    normalize: bool = True


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: List[float]


class EmbeddingResponse(BaseModel):
    object: str = "list"
    model: str
    data: List[EmbeddingData]
    usage: dict = Field(default_factory=dict)


class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    model: str = DEFAULT_RERANK_MODEL
    top_n: int = 30


class RerankResult(BaseModel):
    index: int
    score: float
    text: str


class RerankResponse(BaseModel):
    model: str
    results: List[RerankResult]
    usage: dict = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        "rerank_model": DEFAULT_RERANK_MODEL,
        "hf_endpoint": os.getenv("HF_ENDPOINT", ""),
        "modelscope_cache": os.getenv("MODELSCOPE_CACHE", ""),
    }


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def embeddings(request: EmbeddingRequest) -> EmbeddingResponse:
    texts = [request.input] if isinstance(request.input, str) else list(request.input)
    if not texts:
        raise HTTPException(status_code=400, detail="input is empty")
    started = time.perf_counter()
    model = get_embedding_model(request.model)
    vectors = model.encode(texts, normalize_embeddings=request.normalize)
    if isinstance(vectors, dict) and "dense_vecs" in vectors:
        vectors = vectors["dense_vecs"]
    vectors = vectors.tolist() if hasattr(vectors, "tolist") else vectors
    return EmbeddingResponse(
        model=request.model,
        data=[
            EmbeddingData(index=idx, embedding=[float(value) for value in vector])
            for idx, vector in enumerate(vectors)
        ],
        usage={
            "prompt_tokens": sum(len(text) for text in texts),
            "total_tokens": sum(len(text) for text in texts),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )


@app.post("/v1/rerank", response_model=RerankResponse)
def rerank(request: RerankRequest) -> RerankResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query is empty")
    if not request.documents:
        return RerankResponse(model=request.model, results=[])
    started = time.perf_counter()
    model = get_reranker(request.model)
    pairs = [[request.query, doc] for doc in request.documents]
    if hasattr(model, "compute_score"):
        scores = model.compute_score(pairs, normalize=True)
    else:
        scores = model.predict(pairs)
    if isinstance(scores, float):
        scores = [scores]
    ranked = sorted(
        [
            RerankResult(index=idx, score=float(score), text=request.documents[idx])
            for idx, score in enumerate(scores)
        ],
        key=lambda item: item.score,
        reverse=True,
    )[: max(int(request.top_n), 0)]
    return RerankResponse(
        model=request.model,
        results=ranked,
        usage={
            "document_count": len(request.documents),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )


@lru_cache(maxsize=4)
def get_embedding_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_resolve_model_path(model_name), trust_remote_code=True)


@lru_cache(maxsize=4)
def get_reranker(model_name: str):
    if "Qwen3-Reranker" in model_name:
        return QwenCausalReranker(_resolve_model_path(model_name))
    from sentence_transformers import CrossEncoder

    return CrossEncoder(_resolve_model_path(model_name), trust_remote_code=True)


class QwenCausalReranker:
    def __init__(self, model_path: str, max_length: int = 8192, batch_size: int = 4) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.max_length = max_length
        self.batch_size = int(os.getenv("RERANK_BATCH_SIZE", str(batch_size)))
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            device_map="auto" if torch.cuda.is_available() else None,
            torch_dtype="auto",
            trust_remote_code=True,
        )
        self.model.eval()
        self.token_false_id = self.tokenizer.convert_tokens_to_ids("no")
        self.token_true_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.prefix = (
            "<|im_start|>system\n"
            'Judge whether the Document meets the requirements based on the Query. '
            'The answer can only be "yes" or "no".<|im_end|>\n'
            "<|im_start|>user\n"
        )
        self.suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self.prefix_tokens = self.tokenizer.encode(self.prefix, add_special_tokens=False)
        self.suffix_tokens = self.tokenizer.encode(self.suffix, add_special_tokens=False)

    def compute_score(self, pairs: list[list[str]], normalize: bool = True) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start : start + self.batch_size]
            scores.extend(self._compute_batch(batch, normalize=normalize))
        return scores

    def _compute_batch(self, pairs: list[list[str]], normalize: bool) -> list[float]:
        query_docs = [
            f"<Query>: {query}\n<Document>: {document}"
            for query, document in pairs
        ]
        inputs = self.tokenizer(
            query_docs,
            padding=False,
            truncation="longest_first",
            return_attention_mask=False,
            max_length=self.max_length - len(self.prefix_tokens) - len(self.suffix_tokens),
        )
        input_ids = [
            self.prefix_tokens + ids + self.suffix_tokens
            for ids in inputs["input_ids"]
        ]
        padded = self.tokenizer.pad(
            {"input_ids": input_ids},
            padding=True,
            return_attention_mask=True,
            return_tensors="pt",
            max_length=self.max_length,
        )
        device = self.model.device
        padded = {key: value.to(device) for key, value in padded.items()}
        with self.torch.no_grad():
            logits = self.model(**padded).logits[:, -1, :]
            true_scores = logits[:, self.token_true_id]
            false_scores = logits[:, self.token_false_id]
            if normalize:
                pair_scores = self.torch.stack([false_scores, true_scores], dim=1)
                return self.torch.nn.functional.softmax(pair_scores, dim=1)[:, 1].tolist()
            return true_scores.tolist()


def _resolve_model_path(model_name: str) -> str:
    if MODEL_PATHS.exists():
        try:
            paths = json.loads(MODEL_PATHS.read_text(encoding="utf-8"))
            local_path = paths.get(model_name)
            if local_path and Path(local_path).exists():
                return local_path
        except Exception:
            pass
    safe_name = model_name.replace("/", "__")
    candidate = ROOT_DIR / "models" / safe_name
    if candidate.exists():
        return str(candidate)
    return model_name
