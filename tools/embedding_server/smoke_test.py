from __future__ import annotations

import json
import urllib.request


BASE_URL = "http://127.0.0.1:18080"


def post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    health = get_json("/health")
    print("health:", health)

    embeddings = post_json(
        "/v1/embeddings",
        {
            "input": ["测试中文小说检索：角色隐瞒真相，剧情线逐渐收束。"],
            "model": "Qwen/Qwen3-Embedding-4B",
        },
    )
    vector = embeddings["data"][0]["embedding"]
    print("embedding_dimension:", len(vector))

    rerank = post_json(
        "/v1/rerank",
        {
            "query": "主角发现旧日誓言与当前计划冲突",
            "documents": [
                "主角在雨夜想起旧日誓言，意识到自己的计划可能伤害同伴。",
                "城里的商铺正在准备节庆，街道上挂满灯笼。",
            ],
            "model": "Qwen/Qwen3-Reranker-4B",
            "top_n": 2,
        },
    )
    print("rerank:", rerank)


if __name__ == "__main__":
    main()
