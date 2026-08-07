"""Memory. Spec section 7, four tiers.

    1  vault/profile.md   hand-written by you, ~1500 tokens, injected into EVERY prompt.
                          Never generated. Honcho proposes; you approve.
    2  episodic.db        append-only, never edited, only compressed.
    3  vault/             markdown, written by the consolidation loop, editable by you.
    4  Qdrant + FTS5      hybrid retrieval, bge-reranker-v2-m3 on top.

The tier easiest to get wrong is 3, and the way it goes wrong is ADR-0007: **bounded memory
means consolidate when full.** The write path blocks. It is not a nightly compression job,
and building it as one produces something that works for six weeks and then degrades on a
curve nobody is watching.

Spec section 10 names the failure it prevents: retrieval collapse around 10k documents. The
reranker and the consolidation loop are what save you, which is why both are in week 3 and
not week 8.

Implemented in W3 (docs/weeks/W3.md).
"""
