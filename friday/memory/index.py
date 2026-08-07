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

from friday.models import Chunk, Sensitivity


def create_collection() -> None:
    """Create the Qdrant collection at the configured dimension. Idempotent.

    Refuses to recreate an existing collection at a DIFFERENT dimension. That operation
    destroys every vector and should be a deliberate command, not a side effect of someone
    editing a config key.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.index.create_collection is implemented in W3")


def embed(texts: list[str]) -> list[list[float]]:
    """Embed via the `embed` alias through LiteLLM.

    No fallback, deliberately. config/litellm.yaml gives `daily` and `coder` fallbacks and
    gives `embed` and `rerank` none: silently answering with a different embedding model
    produces vectors from a different space, which degrades quietly and is very hard to
    diagnose from an eval score alone. Better to fail.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.index.embed is implemented in W3")


def upsert(chunks: list[Chunk]) -> int:
    """Embed and upsert. Returns points written. Keyed on chunk_id, so re-running is safe.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.index.upsert is implemented in W3")


def search(query: str, limit: int = 30, sensitivity: Sensitivity | None = None) -> list[Chunk]:
    """Vector search. The vector half of spec section 7's parallel retrieval.

    `sensitivity` becomes a Qdrant filter ON the query, not a post-filter on results.
    ADR-0008, same reason as the keyword side.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.index.search is implemented in W3")


def rerank(query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
    """Rerank with bge-reranker-v2-m3. The step that saves you at 10k documents.

    Spec section 10 predicts retrieval collapse around 10k documents and names the reranker
    and the consolidation loop as what save you - which is why both are in week 3.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.index.rerank is implemented in W3")
