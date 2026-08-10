"""Retrieval. Spec section 7, and the order is not negotiable.

    expand query -> parallel keyword + vector (top 30 each) -> dedupe -> rerank to top 8
    -> recency boost

Two steps get reordered by accident and both have the same symptom: the eval drops three
points and the pipeline still looks like section 7 at a glance.

**Keyword and vector are parallel, not sequential.** They are independent, and W5's 800ms
budget does not survive them being serial.

**The recency boost is applied AFTER reranking.** Before it, a recent irrelevant document
outranks an old exact answer, and the eval fails on exactly the temporal questions.

Three things are injected unconditionally rather than retrieved: the current date and time,
today's calendar, and profile.md. Spec section 7 - local models are hopeless at temporal
reasoning otherwise - and spec section 10, resolve dates in code, never in the prompt.
Retrieval can miss; these cannot be allowed to.

Implemented in W3.
"""

from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from friday.config import get
from friday.models import Chunk, Retrieved, Sensitivity

logger = logging.getLogger(__name__)


def _get_openai_client():
    from openai import OpenAI

    cfg = get()
    base_url = cfg.friday.models.litellm_base_url
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return OpenAI(base_url=base_url, api_key="sk-friday-internal")


def expand(query: str, n: int = 3) -> list[str]:
    """Expand a query into paraphrases. Runs on `fast`.

    Your phrasing and the corpus's phrasing rarely match, and this is the cheapest available
    fix - usually worth about two eval points.
    """
    n = n or get().memory.retrieve.expansions

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="fast",
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Generate {n} alternative phrasings of this query, each on its own "
                        f"line. Do not number them. Do not add commentary. Just the "
                        f"paraphrases.\n\nQuery: {query}"
                    ),
                }
            ],
            max_tokens=500,
            temperature=0.3,
        )
        raw = response.choices[0].message.content or ""
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        # Remove leading numbers if present
        lines = [re.sub(r"^\d+[\.\)]\s*", "", l) for l in lines]
        return lines[:n]
    except Exception as e:
        logger.warning("expand failed, using original query only: %s", e)
        return [query]


def _rrf(rank: int, k: int = 60) -> float:
    """Reciprocal Rank Fusion score for a given rank."""
    return 1.0 / (k + rank)


def retrieve(
    query: str,
    now: datetime,
    sensitivity: Sensitivity | None = None,
    explain: bool = False,
) -> list[Retrieved]:
    """The full pipeline, in spec section 7's order.

    Args:
        query: The user's question, unexpanded.
        now: Reference time, passed in rather than read. This module does not touch the clock,
            so a result is reproducible from a stored run - which is what makes the eval a
            measurement rather than an observation.
        sensitivity: Applied INSIDE both searches, never after ranking (ADR-0008).
        explain: Keep every stage's survivors and scores on the result. Build this in W3
            rather than later: it is the only tool that says which stage dropped the answer,
            and in W4 it is the only thing that says which new source broke the eval.

    Anything below `min_rerank_score` is dropped even when the context window has room.
    Padding the context to use the budget is exactly how retrieval degrades invisibly.
    """
    from friday.memory import episodic, index

    cfg = get()
    retrieve_cfg = cfg.memory.retrieve

    # 1. Expand the query
    expansions = expand(query, n=retrieve_cfg.expansions)
    all_queries = [query] + expansions

    # 2. Parallel keyword + vector search
    # Keyword search: run FTS5 for each expanded query
    # Vector search: embed the original query, search Qdrant

    def _keyword_search(q: str) -> list[dict]:
        return episodic.search(
            q, limit=retrieve_cfg.keyword_k, sensitivity=sensitivity
        )

    def _vector_search(q: str) -> list[Chunk]:
        return index.search(
            q, limit=retrieve_cfg.vector_k, sensitivity=sensitivity
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        keyword_future = pool.submit(_keyword_search, query)
        vector_future = pool.submit(_vector_search, query)

        keyword_results = keyword_future.result()
        vector_results = vector_future.result()

    # Also run keyword search for each expansion and merge
    for eq in expansions:
        keyword_results.extend(
            episodic.search(eq, limit=retrieve_cfg.keyword_k, sensitivity=sensitivity)
        )

    # Dedupe: merge by (source, external_id) keeping best rank
    # Keyword results: assign ranks
    keyword_ranked: dict[tuple[str, str], int] = {}
    for rank, r in enumerate(keyword_results):
        key = (r["source"], r["external_id"])
        if key not in keyword_ranked:
            keyword_ranked[key] = rank

    # Vector results: assign ranks
    vector_ranked: dict[tuple[str, str], int] = {}
    for rank, c in enumerate(vector_results):
        key = (c.source, c.external_id)
        if key not in vector_ranked:
            vector_ranked[key] = rank

    # 3. Dedupe and fuse with RRF
    all_keys = set(keyword_ranked.keys()) | set(vector_ranked.keys())

    fused: list[tuple[tuple[str, str], float, int | None, int | None]] = []
    for key in all_keys:
        k_rank = keyword_ranked.get(key)
        v_rank = vector_ranked.get(key)
        rrf_score = 0.0
        if k_rank is not None:
            rrf_score += _rrf(k_rank)
        if v_rank is not None:
            rrf_score += _rrf(v_rank)
        fused.append((key, rrf_score, k_rank, v_rank))

    # Sort by fused score descending
    fused.sort(key=lambda x: x[1], reverse=True)

    # Build Chunk objects for all fused results
    # For keyword results, build Chunk from the dict
    keyword_by_key = {(r["source"], r["external_id"]): r for r in keyword_results}
    vector_by_key = {(c.source, c.external_id): c for c in vector_results}

    fused_chunks: list[Chunk] = []
    ranks_map: dict[tuple[str, str], tuple[int | None, int | None, float]] = {}

    for key, rrf_score, k_rank, v_rank in fused:
        if key in vector_by_key:
            chunk = vector_by_key[key]
        elif key in keyword_by_key:
            r = keyword_by_key[key]
            chunk = Chunk(
                chunk_id=r["id"],
                source=r["source"],
                external_id=r["external_id"],
                occurred_at=datetime.fromisoformat(r["occurred_at"]),
                sensitivity=Sensitivity(r["sensitivity"]),
                text=r["body"],
                meta=r.get("meta", {}),
            )
        else:
            continue
        fused_chunks.append(chunk)
        ranks_map[key] = (k_rank, v_rank, rrf_score)

    # 4. Rerank to top rerank_to
    rerank_to = retrieve_cfg.rerank_to
    candidates = fused_chunks[: max(rerank_to * 3, 30)]  # rerank a bit more than needed

    reranked: list[tuple[Chunk, float]] = []
    if candidates:
        try:
            reranked = index.rerank(query, candidates)
        except Exception as e:
            logger.warning("rerank failed, using fused scores: %s", e)
            # Fallback: use fused scores
            for chunk in candidates:
                key = (chunk.source, chunk.external_id)
                reranked.append((chunk, ranks_map[key][2]))

    # Drop below min_rerank_score
    min_score = retrieve_cfg.min_rerank_score
    reranked = [(c, s) for c, s in reranked if s >= min_score]

    # Limit to rerank_to
    reranked = reranked[:rerank_to]

    # 5. Recency boost AFTER reranking
    half_life = retrieve_cfg.recency_half_life_days
    do_boost = retrieve_cfg.recency_boost

    results: list[Retrieved] = []
    for chunk, rerank_score in reranked:
        key = (chunk.source, chunk.external_id)
        k_rank, v_rank, rrf_score = ranks_map.get(key, (None, None, None))

        final_score = rerank_score
        if do_boost:
            age_days = (now - chunk.occurred_at).total_seconds() / 86400
            boost = math.exp(-age_days / half_life)
            final_score = rerank_score * (1 + boost)

        results.append(
            Retrieved(
                chunk=chunk,
                keyword_rank=k_rank,
                vector_rank=v_rank,
                fused_score=rrf_score,
                rerank_score=rerank_score,
                final_score=final_score,
            )
        )

    # Sort by final score
    results.sort(key=lambda r: r.final_score or 0, reverse=True)

    return results


def build_context(results: list[Retrieved], now: datetime) -> str:
    """Assemble prompt context: profile, date and time, today's calendar, then results.

    Carries source and timestamp on every chunk (`carry_provenance`) and marks anything older
    than `stale_after_days`, so the answer is qualified rather than asserted.
    """
    cfg = get()
    parts: list[str] = []

    # 1. Profile (always injected, never retrieved)
    try:
        from friday.memory import vault

        profile_text = vault.profile()
        if profile_text:
            parts.append(f"## Profile\n\n{profile_text}")
    except Exception as e:
        logger.warning("could not read profile: %s", e)

    # 2. Current date and time (always injected, never retrieved)
    parts.append(f"## Current Date and Time\n\n{now.isoformat()}")

    # 3. Today's calendar (always injected, never retrieved)
    # In W3 we don't have the calendar integration yet, but the spec says to inject it
    # For now, inject a placeholder that the caller can fill
    today_str = now.date().isoformat()
    parts.append(f"## Today's Calendar ({today_str})\n\n[calendar injection point]")

    # 4. Results with provenance
    stale_after = cfg.memory.retrieve.stale_after_days
    results_parts: list[str] = []
    for r in results:
        provenance = (
            f"[source={r.chunk.source} occurred_at={r.chunk.occurred_at.isoformat()}"
        )
        age_days = (now - r.chunk.occurred_at).total_seconds() / 86400
        if age_days > stale_after:
            provenance += " STALE"
        provenance += "]"

        if cfg.memory.retrieve.carry_provenance:
            results_parts.append(f"{provenance}\n{r.chunk.text}")
        else:
            results_parts.append(r.chunk.text)

    if results_parts:
        parts.append("## Retrieved Context\n\n" + "\n\n---\n\n".join(results_parts))

    return "\n\n".join(parts)
