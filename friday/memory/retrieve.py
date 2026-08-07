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

from datetime import datetime

from friday.models import Retrieved, Sensitivity


def expand(query: str, n: int = 3) -> list[str]:
    """Expand a query into paraphrases. Runs on `fast`.

    Your phrasing and the corpus's phrasing rarely match, and this is the cheapest available
    fix - usually worth about two eval points.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.retrieve.expand is implemented in W3")


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

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.retrieve.retrieve is implemented in W3")


def build_context(results: list[Retrieved], now: datetime) -> str:
    """Assemble prompt context: profile, date and time, today's calendar, then results.

    Carries source and timestamp on every chunk (`carry_provenance`) and marks anything older
    than `stale_after_days`, so the answer is qualified rather than asserted.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.retrieve.build_context is implemented in W3")
