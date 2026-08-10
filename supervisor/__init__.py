"""The supervisor. Spec section 9, ADR-0004, ADR-0009.

~150 lines, different user, outside her reach. Health-checks every 30s, reverts
to last-known-good after three consecutive failures, kills over-budget tasks,
hard-stops if agent/core/ is modified, and only advances the known-good tag
after a full eval pass.

It MUST NOT import friday.* — importing the code it polices inherits that code's
surface area and its dependencies, and a crash in a retrieval library then takes
down the thing that was supposed to notice.

Six behaviours:
  1. health check      every 30s: preflight --quiet + liveness per managed unit
  2. revert            3 consecutive failures -> git checkout known-good, restart
  3. budget kill       tokens and wall clock per task. SIGTERM, grace, SIGKILL
  4. core immutability hash agent/core/. Any change -> hard stop
  5. known-good gate   advance tag only after make eval passes
  6. kill switch       phone over mesh, and physical button
"""

from supervisor.main import main

__all__ = ["main"]
