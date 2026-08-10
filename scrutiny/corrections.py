"""The correction ledger. Spec section 10.

"Scrutiny false positives. She'll flag your complaining as a brainstorm. Log every
correction from day one - that's your fine-tuning set."

What a correction records, and why each field is needed:

    decision_id      which decision
    rule             WHICH RULE fired. The useful signal. An aggregate agreement rate is
                     nearly useless; one rule being wrong 40% of the time is the finding,
                     and it hides inside a healthy total.
    scores           the seven axes as scored. Distinguishes a bad rule from a bad score:
                     if the scores were right and the action was wrong, fix the table; if
                     the scores were wrong, fix the prompt.
    action_taken     what she did
    action_wanted    what you wanted
    note             optional, from you

Recording only `action_wanted` teaches nothing. That is the whole reason this module
exists as more than an UPDATE statement.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scrutiny.policy import Action
from scrutiny.score import Score


class CorrectionError(Exception):
    """Raised on a failed correction write: unknown decision id, already corrected."""


# Schema for both tables. Decisions are written by the daemon on EVERY signal, not only
# on corrected ones — the denominator of the accuracy report is every decision.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id            TEXT PRIMARY KEY,
    ts            TEXT NOT NULL,
    signal_id     TEXT NOT NULL,
    rule          TEXT NOT NULL,
    action        TEXT NOT NULL,
    scores_json   TEXT NOT NULL,
    context_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corrections (
    id             TEXT PRIMARY KEY,
    decision_id    TEXT NOT NULL REFERENCES decisions(id),
    ts             TEXT NOT NULL,
    rule           TEXT NOT NULL,
    action_taken   TEXT NOT NULL,
    action_wanted  TEXT NOT NULL,
    scores_json    TEXT NOT NULL,
    note           TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_decisions_signal ON decisions(signal_id);
CREATE INDEX IF NOT EXISTS idx_corrections_decision ON corrections(decision_id);
CREATE INDEX IF NOT EXISTS idx_corrections_rule ON corrections(rule);
"""


def _db_path(path: str | None = None) -> str:
    """Resolve the scrutiny DB path.

    If ``path`` is given, use it directly. Otherwise read it from
    ``config/scrutiny.yaml``'s ``corrections.db`` key. If that is unavailable, fall
    back to ``friday.config.get()``.
    """
    if path is not None:
        return path
    # Try config/scrutiny.yaml first.
    try:
        import yaml

        from friday.config import repo_root

        scrutiny_path = repo_root() / "config" / "scrutiny.yaml"
        raw = yaml.safe_load(scrutiny_path.read_text())
        db = raw.get("corrections", {}).get("db")
        if db:
            return db
    except Exception:
        pass
    # Last resort: the production path.
    return "/srv/friday/db/scrutiny.db"


def _connect(path: str | None = None) -> sqlite3.Connection:
    """Open a connection to the scrutiny DB, ensuring the schema exists."""
    db_path = _db_path(path)
    # Ensure parent directory exists (tests may use a temp path).
    parent = Path(db_path).parent
    if parent and str(parent) != "":
        parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def init_db(path: str | None = None) -> None:
    """Create the corrections schema. Idempotent.

    Schema:
        decisions(id, ts, signal_id, rule, action, scores_json, context_json)
        corrections(id, decision_id, ts, rule, action_taken, action_wanted, scores_json, note)

    Decisions are written by the daemon on every signal, not only on corrected ones: the
    denominator of the agreement rate is every decision, and a ledger of only the mistakes
    cannot compute it.

    Implemented in week 7.
    """
    conn = _connect(path)
    conn.close()


def record_decision(
    signal_id: str,
    rule: str,
    action: Action,
    scores: Score,
    context: Mapping[str, Any] | None = None,
    *,
    db_path: str | None = None,
    decision_id: str | None = None,
    ts: str | None = None,
) -> str:
    """Write a decision row to the ledger. Returns the decision id.

    Called by the daemon for EVERY signal, not only interesting ones. The denominator of
    the accuracy report is every decision.

    ``db_path`` and ``decision_id`` and ``ts`` are for testing; in production they
    default to the configured DB and a new UUID and the current UTC timestamp.
    """
    conn = _connect(db_path)
    try:
        did = decision_id or str(uuid.uuid4())
        timestamp = ts or datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(id, ts, signal_id, rule, action, scores_json, context_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                did,
                timestamp,
                signal_id,
                rule,
                action.value,
                json.dumps(scores.as_dict()),
                json.dumps(dict(context or {}), default=str),
            ),
        )
        conn.commit()
        return did
    finally:
        conn.close()


def record_correction(
    decision_id: str,
    action_wanted: Action,
    note: str | None = None,
    *,
    db_path: str | None = None,
    correction_id: str | None = None,
    ts: str | None = None,
) -> str:
    """Record a human override against a decision. Returns the correction id.

    Looks up the decision to capture the rule and the scores alongside the override, so a
    correction is self-contained: readable months later without joining against a table
    that may have been pruned.

    Correcting an already-corrected decision raises rather than recording a second row, so
    a double-click in the UI does not skew the accuracy report.

    Implemented in week 7.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, rule, action, scores_json FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise CorrectionError(f"no decision with id {decision_id!r}")

        existing = conn.execute(
            "SELECT id FROM corrections WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        if existing is not None:
            raise CorrectionError(
                f"decision {decision_id!r} already corrected (correction {existing['id']!r})"
            )

        cid = correction_id or str(uuid.uuid4())
        timestamp = ts or datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO corrections "
            "(id, decision_id, ts, rule, action_taken, action_wanted, scores_json, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cid,
                decision_id,
                timestamp,
                row["rule"],
                row["action"],
                action_wanted.value,
                row["scores_json"],
                note,
            ),
        )
        conn.commit()
        return cid
    finally:
        conn.close()


def accuracy_by_rule(
    days: int = 30,
    *,
    db_path: str | None = None,
) -> list[Mapping[str, Any]]:
    """Per-rule agreement rate over a window. One row per rule that fired.

    Reports review volume next to agreement rate. A period with no corrections means
    either good triage or an inbox nobody read, and those must not look the same.

    Watch the `floor` rule specifically: a climbing floor rate means signals are falling
    through every rule in the table, which is a gap rather than a tuning problem.

    Implemented in week 7.
    """
    conn = _connect(db_path)
    try:
        since = (
            datetime.now(UTC) - _timedelta_days(days)
        ).isoformat()
        # Total decisions per rule in the window.
        totals = conn.execute(
            "SELECT rule, COUNT(*) AS total FROM decisions "
            "WHERE ts >= ? GROUP BY rule ORDER BY total DESC",
            (since,),
        ).fetchall()
        # Corrections per rule in the window.
        corrected = conn.execute(
            "SELECT rule, COUNT(*) AS cnt FROM corrections "
            "WHERE ts >= ? GROUP BY rule",
            (since,),
        ).fetchall()
        corrected_map: dict[str, int] = {r["rule"]: r["cnt"] for r in corrected}

        results: list[Mapping[str, Any]] = []
        for row in totals:
            rule = row["rule"]
            total = row["total"]
            n_corrected = corrected_map.get(rule, 0)
            agreement_rate = (total - n_corrected) / total if total > 0 else 1.0
            results.append(
                {
                    "rule": rule,
                    "total": total,
                    "corrected": n_corrected,
                    "agreement_rate": agreement_rate,
                    "review_volume": n_corrected,
                }
            )
        return results
    finally:
        conn.close()


def export_finetune_set(
    path: str,
    *,
    db_path: str | None = None,
) -> int:
    """Export the corrections as a training set. Returns the number of examples.

    Spec section 10 calls this out explicitly: the corrections ARE the fine-tuning set.
    Each example is the signal, the seven scores, the rule that fired, and the action you
    wanted.

    Implemented after week 8, once there is enough volume for it to mean anything.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT d.signal_id, d.scores_json, d.context_json, c.rule, c.action_wanted "
            "FROM corrections c JOIN decisions d ON c.decision_id = d.id"
        ).fetchall()

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with out_path.open("w") as f:
            for row in rows:
                example = {
                    "signal_id": row["signal_id"],
                    "scores": json.loads(row["scores_json"]),
                    "context": json.loads(row["context_json"]),
                    "rule_fired": row["rule"],
                    "action_wanted": row["action_wanted"],
                }
                f.write(json.dumps(example) + "\n")
                count += 1
        return count
    finally:
        conn.close()


def _timedelta_days(days: int):
    from datetime import timedelta

    return timedelta(days=days)
