# Novel Embedding Service

GPU-side service for Phase 3 retrieval.

Recommended remote path:

```bash
/home/data/nas_hdd/jinglong/waf/novel-embedding-service
```

Domestic download settings:

```bash
export HF_HOME=/home/data/nas_hdd/jinglong/waf/novel-embedding-service/cache/huggingface
export TRANSFORMERS_CACHE=/home/data/nas_hdd/jinglong/waf/novel-embedding-service/cache/huggingface
export MODELSCOPE_CACHE=/home/data/nas_hdd/jinglong/waf/novel-embedding-service/cache/modelscope
```

Install:

```bash
/home/jinglong/miniconda/bin/conda create -y -p /home/data/nas_hdd/jinglong/waf/conda-envs/novel_embedding_waf python=3.10
/home/data/nas_hdd/jinglong/waf/conda-envs/novel_embedding_waf/bin/python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

Start:

```bash
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B RERANK_MODEL=Qwen/Qwen3-Reranker-4B CUDA_VISIBLE_DEVICES=0 ./start.sh
```

APIs:

```text
GET  /health
POST /v1/embeddings
POST /v1/rerank
```
