"""The triage daemon. Wires senses to scoring to dispatch.

Loop, per signal from sources.db:

    1. Look up novelty context: has the vault already recorded this? Read-only.
    2. score_signal() on `fast`, tools [], 400 tokens.
    3. decide() against the table. Pure, deterministic, names the rule.
    4. Write the decision to scrutiny.db - EVERY decision, not only interesting ones.
       The denominator of the accuracy report is every decision.
    5. Dispatch:
         act        execute, then report
         ask        inbox, and wait. No timeout converts an ask into an action.
         watch      re-evaluate on new information, or after the configured interval
         ignore     logged and dropped. Still written to scrutiny.db.
         propagate  hand to a bounded specialist with a budget, allowlist and branch

Step 4 before step 5 is not an ordering detail. A decision that is acted on before it is
recorded is a decision you cannot audit if the action goes wrong.

Spec section 6 puts this at week 7, after memory, voice and tools. Do not reorder: novelty
is meaningless against an empty vault, and specificity cannot be judged without knowing
what tools exist to act with.

Runs as `friday` under friday-scrutiny.service.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scrutiny.corrections import record_decision
from scrutiny.policy import Action, Decision, RuleTable, decide, load_table
from scrutiny.score import Score, score_signal

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """One unprocessed row from sources.db, as the daemon sees it.

    ``signal_id`` is the stable id used in the decisions ledger. ``body`` is already
    wrapped (friday.models.wrap_untrusted) by the ingest layer. ``context`` carries
    channel, kind, speaker_verified and anything else the rule table reads via
    ``context.*``.
    """

    signal_id: str
    body: str
    context: dict[str, Any]


@dataclass
class DaemonResult:
    """The outcome of processing one signal — returned for testing and logging.

    ``decision_id`` is the row written to scrutiny.db. ``dispatched`` is True once the
    dispatch handler has been called.
    """

    signal_id: str
    score: Score
    decision: Decision
    decision_id: str
    dispatched: bool


def _default_sources_db_path() -> str:
    try:
        from friday.config import get

        return str(get().sources.defaults.sink)
    except Exception:
        return "/srv/friday/db/sources.db"


def _ensure_processed_table(conn: sqlite3.Connection) -> None:
    """Create the tracking table that marks signals as processed.

    A signal is identified by ``(source, external_id)`` in sources.db. We track the
    composite key to avoid re-scoring on every loop iteration.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scrutiny_processed (
            signal_id   TEXT PRIMARY KEY,
            ts          TEXT NOT NULL,
            decision_id TEXT NOT NULL
        );
        """
    )


def _read_unprocessed_signals(
    sources_db: str,
    *,
    limit: int = 100,
) -> list[Signal]:
    """Read signals from sources.db that have not been processed by scrutiny yet.

    The events table in sources.db has columns:
        source, external_id, occurred_at, body, sensitivity, untrusted, meta, ingested_at

    The ``signal_id`` is constructed as ``f"{source}:{external_id}"``.
    """
    if not Path(sources_db).is_file():
        return []

    conn = sqlite3.connect(sources_db)
    conn.row_factory = sqlite3.Row
    _ensure_processed_table(conn)
    try:
        rows = conn.execute(
            "SELECT e.source, e.external_id, e.body, e.meta "
            "FROM events e "
            "LEFT JOIN scrutiny_processed sp ON sp.signal_id = e.source || ':' || e.external_id "
            "WHERE sp.signal_id IS NULL "
            "ORDER BY e.occurred_at ASC "
            "LIMIT ?",
            (limit,),
        ).fetchall()

        signals: list[Signal] = []
        for row in rows:
            meta: dict[str, Any] = {}
            if row["meta"]:
                try:
                    meta = json.loads(row["meta"])
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            signals.append(
                Signal(
                    signal_id=f"{row['source']}:{row['external_id']}",
                    body=row["body"] or "",
                    context=meta,
                )
            )
        return signals
    finally:
        conn.close()


def _mark_processed(
    sources_db: str,
    signal_id: str,
    decision_id: str,
) -> None:
    """Mark a signal as processed in the tracking table."""
    conn = sqlite3.connect(sources_db)
    conn.execute(
        "INSERT OR REPLACE INTO scrutiny_processed (signal_id, ts, decision_id) "
        "VALUES (?, ?, ?)",
        (signal_id, datetime.now(UTC).isoformat(), decision_id),
    )
    conn.commit()
    conn.close()


def _dispatch(
    decision: Decision,
    signal: Signal,
    score: Score,
) -> bool:
    """Dispatch according to the decision's action.

    In this implementation, dispatch is a log entry. The real execution (act, propagate
    to a specialist, etc.) is handled by other subsystems. This function is the seam:
    tests can replace it with a mock to assert dispatch behaviour.

    Returns True if the dispatch handler ran.
    """
    action = decision.action
    if action is Action.ACT:
        logger.info("dispatch act: %s -> execute and report", signal.signal_id)
    elif action is Action.ASK:
        logger.info("dispatch ask: %s -> inbox, waiting", signal.signal_id)
    elif action is Action.WATCH:
        logger.info("dispatch watch: %s -> re-evaluate later", signal.signal_id)
    elif action is Action.IGNORE:
        logger.info("dispatch ignore: %s -> logged and dropped", signal.signal_id)
    elif action is Action.PROPAGATE:
        logger.info("dispatch propagate: %s -> specialist", signal.signal_id)
    return True


def process_signal(
    signal: Signal,
    *,
    table: RuleTable | None = None,
    score_fn: Callable[..., Score] | None = None,
    scrutiny_db: str | None = None,
    sources_db: str | None = None,
    dispatch_fn: Callable[[Decision, Signal, Score], bool] | None = None,
) -> DaemonResult:
    """Process one signal through the full pipeline.

    This is the testable core of the daemon, extracted so tests can exercise it without
    a running loop, database or model.

    Steps (in order, per the module docstring):
      1. Score the signal (model call, or ``score_fn`` if given).
      2. Decide against the table (pure).
      3. Write the decision to scrutiny.db.
      4. Dispatch.
    """
    if table is None:
        table = load_table()

    if score_fn is None:
        score_fn = score_signal

    # Step 1-2: score
    score = score_fn(signal.body, signal.context)

    # Step 3: decide (pure, deterministic)
    decision = decide(score, signal.context, table)

    # Step 4: write the decision BEFORE dispatching
    decision_id = record_decision(
        signal_id=signal.signal_id,
        rule=decision.rule,
        action=decision.action,
        scores=score,
        context=signal.context,
        db_path=scrutiny_db,
    )

    # Step 5: dispatch
    dispatched = False
    if dispatch_fn is not None:
        dispatched = dispatch_fn(decision, signal, score)
    else:
        dispatched = _dispatch(decision, signal, score)

    return DaemonResult(
        signal_id=signal.signal_id,
        score=score,
        decision=decision,
        decision_id=decision_id,
        dispatched=dispatched,
    )


def run_once(
    *,
    sources_db: str | None = None,
    scrutiny_db: str | None = None,
    table: RuleTable | None = None,
    score_fn: Callable[..., Score] | None = None,
    dispatch_fn: Callable[[Decision, Signal, Score], bool] | None = None,
    batch_limit: int = 100,
) -> list[DaemonResult]:
    """Process one batch of unprocessed signals. Returns the results.

    Does not loop; processes at most ``batch_limit`` signals that have not yet been
    processed by scrutiny.
    """
    sdb = sources_db or _default_sources_db_path()
    signals = _read_unprocessed_signals(sdb, limit=batch_limit)
    results: list[DaemonResult] = []
    for signal in signals:
        try:
            result = process_signal(
                signal,
                table=table,
                score_fn=score_fn,
                scrutiny_db=scrutiny_db,
                sources_db=sdb,
                dispatch_fn=dispatch_fn,
            )
            _mark_processed(sdb, signal.signal_id, result.decision_id)
            results.append(result)
        except Exception:
            logger.exception("failed to process signal %s", signal.signal_id)
    return results


def main(argv: list[str] | None = None) -> int:
    """Run the triage loop until terminated. The systemd entry point.

    Implemented in week 7.
    """
    import argparse
    import time

    parser = argparse.ArgumentParser(prog="scrutiny.daemon", description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument("--dry-run", action="store_true", help="Score and decide without dispatching")
    parser.add_argument("--interval", type=float, default=30.0, help="Poll interval in seconds (default 30)")
    parser.add_argument("--batch-limit", type=int, default=100, help="Max signals per batch")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    table = load_table()

    if args.dry_run:
        dispatch_fn: Callable[[Decision, Signal, Score], bool] | None = lambda d, s, sc: False
    else:
        dispatch_fn = None

    if args.once:
        results = run_once(table=table, dispatch_fn=dispatch_fn, batch_limit=args.batch_limit)
        for r in results:
            print(f"{r.signal_id}: {r.decision}")
        return 0

    # Continuous loop
    while True:
        results = run_once(table=table, dispatch_fn=dispatch_fn, batch_limit=args.batch_limit)
        for r in results:
            logger.info("%s: %s", r.signal_id, r.decision)
        time.sleep(args.interval)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
