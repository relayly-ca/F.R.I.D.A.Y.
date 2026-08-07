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


def main(argv: list[str] | None = None) -> int:
    """Run the triage loop until terminated. The systemd entry point.

    Implemented in week 7.
    """
    raise NotImplementedError("scrutiny.daemon.main is implemented in week 7")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
