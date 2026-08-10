"""Ingestion. Spec section 2's SENSES row, landing into sources.db.

Every source is untrusted input. Spec section 9 and ADR-0006: tag it, and the real
boundary is that ingested text reaches a model only through the scorer, which has
``tools: []``.

The base writer owns the untrusted wrap, so no source can forget it. Sources implement
a ``poll()`` that yields ``Event`` objects and never touch ``sources.db`` directly.
"""

from friday.ingest.base import Source, init_db, poll_all, upsert

__all__ = ["Source", "init_db", "upsert", "poll_all"]
