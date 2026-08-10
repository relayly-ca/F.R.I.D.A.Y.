"""Tier 4, vector half. Qdrant, bge-m3, 1024 dimensions.

`embed_dim` is not a tuning parameter. Changing the embedding model is not a re-embed, it is
a rebuild: every existing vector is in a different space and meaningless. Decide on bge-m3
and stay there through W8.

Provenance travels into the payload: source, external id, occurred_at, sensitivity. Spec
section 7 requires it be carried, and it is what lets her say "you told me this in March, it
may be stale" - and, more often useful, what lets you find the source of a wrong answer.

Implemented in W3.
"""

from __future__ import annotations

import logging
from typing import Any

from friday.config import get
from friday.models import Chunk, Sensitivity

logger = logging.getLogger(__name__)


def _get_client():
    """Get a Qdrant client, or None if Qdrant is unreachable."""
    try:
        from qdrant_client import QdrantClient

        cfg = get()
        return QdrantClient(url=cfg.memory.index.qdrant_url)
    except Exception:
        return None


def _get_openai_client():
    """Get an OpenAI client pointed at LiteLLM for embeddings."""
    from openai import OpenAI

    cfg = get()
    base_url = cfg.friday.models.litellm_base_url
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return OpenAI(base_url=base_url, api_key="sk-friday-internal")


def create_collection() -> None:
    """Create the Qdrant collection at the configured dimension. Idempotent.

    Refuses to recreate an existing collection at a DIFFERENT dimension. That operation
    destroys every vector and should be a deliberate command, not a side effect of someone
    editing a config key.
    """
    from qdrant_client.models import Distance, VectorParams

    cfg = get()
    client = _get_client()
    if client is None:
        logger.warning("Qdrant not available; skipping create_collection")
        return

    collection = cfg.memory.index.collection
    dim = cfg.memory.index.embed_dim

    collections = client.get_collections().collections
    existing = {c.name for c in collections}

    if collection in existing:
        info = client.get_collection(collection)
        existing_dim = info.config.params.vectors.size
        if existing_dim != dim:
            raise RuntimeError(
                f"Collection {collection!r} exists at dimension {existing_dim} but "
                f"config says {dim}. Recreating it destroys every vector and must be "
                f"a deliberate command, not a side effect."
            )
        return

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )


def embed(texts: list[str]) -> list[list[float]]:
    """Embed via the `embed` alias through LiteLLM.

    No fallback, deliberately. config/litellm.yaml gives `daily` and `coder` fallbacks and
    gives `embed` and `rerank` none: silently answering with a different embedding model
    produces vectors from a different space, which degrades quietly and is very hard to
    diagnose from an eval score alone. Better to fail.
    """
    cfg = get()
    client = _get_openai_client()
    alias = cfg.memory.index.embed_alias

    response = client.embeddings.create(model=alias, input=texts)
    return [d.embedding for d in response.data]


def upsert(chunks: list[Chunk]) -> int:
    """Embed and upsert. Returns points written. Keyed on chunk_id, so re-running is safe."""
    from qdrant_client.models import PointStruct

    cfg = get()
    client = _get_client()
    if client is None:
        logger.warning("Qdrant not available; skipping upsert")
        return 0

    collection = cfg.memory.index.collection

    texts = [c.text for c in chunks]
    vectors = embed(texts)

    points = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        payload: dict[str, Any] = {
            "source": chunk.source,
            "external_id": chunk.external_id,
            "occurred_at": chunk.occurred_at.isoformat(),
            "sensitivity": chunk.sensitivity.value,
            "text": chunk.text,
            "ordinal": chunk.ordinal,
            "meta": chunk.meta,
        }
        points.append(
            PointStruct(id=chunk.chunk_id, vector=vector, payload=payload)
        )

    client.upsert(collection_name=collection, points=points)
    return len(points)


def search(
    query: str, limit: int = 30, sensitivity: Sensitivity | None = None
) -> list[Chunk]:
    """Vector search. The vector half of spec section 7's parallel retrieval.

    `sensitivity` becomes a Qdrant filter ON the query, not a post-filter on results.
    ADR-0008, same reason as the keyword side.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    cfg = get()
    client = _get_client()
    if client is None:
        logger.warning("Qdrant not available; returning empty search results")
        return []

    collection = cfg.memory.index.collection

    query_vector = embed([query])[0]

    query_filter = None
    if sensitivity is not None:
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="sensitivity",
                    match=MatchValue(value=sensitivity.value),
                )
            ]
        )

    results = client.search(
        collection_name=collection,
        query_vector=query_vector,
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
    )

    chunks = []
    for r in results:
        p = r.payload
        if p is None:
            continue
        from datetime import datetime

        chunks.append(
            Chunk(
                chunk_id=r.id,
                source=p["source"],
                external_id=p["external_id"],
                occurred_at=datetime.fromisoformat(p["occurred_at"]),
                sensitivity=Sensitivity(p["sensitivity"]),
                text=p["text"],
                ordinal=p.get("ordinal", 0),
                meta=p.get("meta", {}),
            )
        )
    return chunks


def rerank(query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
    """Rerank with bge-reranker-v2-m3. The step that saves you at 10k documents.

    Spec section 10 predicts retrieval collapse around 10k documents and names the reranker
    and the consolidation loop as what save you - which is why both are in week 3.
    """
    cfg = get()
    client = _get_openai_client()
    alias = cfg.memory.index.rerank_alias

    if not chunks:
        return []

    documents = [c.text for c in chunks]

    # Use the OpenAI rerank-compatible endpoint (LiteLLM proxy supports this)
    import httpx

    base_url = cfg.friday.models.litellm_base_url
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    response = httpx.post(
        f"{base_url}/rerank",
        json={
            "model": alias,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        },
        timeout=120,
        headers={"Authorization": "sk-friday-internal"},
    )
    response.raise_for_status()
    data = response.json()

    results: list[tuple[Chunk, float]] = []
    for item in data["results"]:
        idx = item["index"]
        score = item["relevance_score"]
        results.append((chunks[idx], score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
