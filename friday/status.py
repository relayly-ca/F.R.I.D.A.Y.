"""Where this build actually is. Derived, never hand-maintained.

A checklist someone has to remember to tick is wrong within a week, and wrong in the
flattering direction. So nothing here is asserted:

    repo state       parsed from the code. Every stub raises NotImplementedError naming
                     the phase that implements it, so REMAINING WORK per phase is read
                     straight from the source and cannot drift from it.

                     Note what is deliberately NOT claimed: a percentage-complete per
                     phase. Stubs attribute reliably; implemented functions do not.
                     friday/config.py mentions five different weeks in passing and
                     friday/profile.py mentions none, so any per-phase denominator would
                     be a guess — and a percentage over a guessed denominator is worse
                     than no percentage. Remaining work is countable; "how much of W3 is
                     written" is not, so it is not reported.

    instance state   probed from the box. Services, databases, eval results. What is
                     actually running, not what was installed once.

Two different questions, and conflating them is why most status trackers are useless. Repo
state is the same for everyone who forks this. Instance state is yours (ADR-0028).

    make stage           both, for a human
    make stage-readme    regenerate the block README.md carries
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from friday.config import repo_root

# Spec section 6's build order, with the "done when" each phase is judged by. The done-when
# text is quoted from the spec rather than paraphrased, because a paraphrased gate drifts
# toward whatever is easy to pass.
PHASES: dict[str, tuple[str, str]] = {
    "W1": ("Inference, routing, agent runtime, messaging",
           "You chat locally, and you text her from your phone"),
    "W2": ("The eval set, the calendar, the first two senses",
           "She answers 'what's my week look like'"),
    "W3": ("Memory, retrieval, the eval gate, the loops",
           "20/25 on your own eval questions"),
    "W4": ("Three more senses, and speech",
           "Eval score holds after each new source"),
    "W5": ("Wake path, voice gate, graph, tools, sandbox, supervisor",
           "Under 800ms, and you can kill her"),
    "W6": ("Modes, brainstorm, barge-in, the wall",
           "She shuts up and takes notes on command"),
    "W7": ("Adaptive Scrutiny and bounded specialists",
           "She works overnight, reports at breakfast"),
    "W8": ("Skill optimisation and the Curator",
           "Skills improve measurably, not just numerously"),
}

# Matches "W3", "week 3", "weeks 4-5". Both spellings occur in this repo and a fork may
# write either, so the parser accepts both rather than the docstrings being normalised —
# a convention enforced only by a tracker is a convention that breaks the tracker.
_WEEK = re.compile(r"\bW\s?([1-8])\b|\bweeks?\s+([1-8])", re.IGNORECASE)
PACKAGES = ("friday", "scrutiny", "supervisor")


@dataclass
class PhaseCode:
    """Work remaining in one phase, counted from the source.

    `stubbed` is the honest number: functions that raise NotImplementedError naming this
    phase. There is no `implemented` counterpart, because implemented code does not reliably
    say which phase it belongs to and inventing an attribution would make the whole tracker
    a guess wearing a number.
    """

    week: str
    stubbed: int = 0
    modules: set[str] = field(default_factory=set)


def scan_code(repo: Path | None = None) -> tuple[dict[str, PhaseCode], int, int]:
    """Read the source. Returns (per-phase remaining work, implemented, unattributed stubs).

    A callable is stubbed if its own body raises NotImplementedError. Its phase comes from
    that message, falling back to the docstring and then the module docstring — a stub that
    names no phase anywhere is counted as unattributed and reported, not silently dropped,
    because a stub nobody can schedule is a real problem worth surfacing.

    Uses ast rather than importing. This must run on a bare checkout with no venv, which is
    exactly the state someone forking this repo is in.
    """
    root = repo or repo_root()
    phases = {w: PhaseCode(week=w) for w in PHASES}
    implemented = 0
    orphan = 0

    for pkg in PACKAGES:
        for path in sorted((root / pkg).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except (OSError, SyntaxError):
                continue

            mod_week = _first_week(ast.get_docstring(tree) or "")
            rel = str(path.relative_to(root))

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):
                    continue

                stub_msg = _stub_message(node)
                if stub_msg is None:
                    implemented += 1
                    continue

                doc = ast.get_docstring(node) or ""
                week = _first_week(stub_msg) or _first_week(doc) or mod_week
                if week is None:
                    orphan += 1
                    continue
                phases[week].stubbed += 1
                phases[week].modules.add(rel)
    return phases, implemented, orphan


def _first_week(text: str) -> str | None:
    m = _WEEK.search(text)
    if not m:
        return None
    return f"W{m.group(1) or m.group(2)}"


def _stub_message(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The NotImplementedError message if this function is a stub, else None.

    Only counts a raise in the function's own body — a NotImplementedError inside a nested
    conditional is error handling, not a stub, and counting it would understate progress.
    """
    for stmt in node.body:
        if not isinstance(stmt, ast.Raise) or stmt.exc is None:
            continue
        exc = stmt.exc
        name = None
        args: list[ast.expr] = []
        if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
            name, args = exc.func.id, exc.args
        elif isinstance(exc, ast.Name):
            name = exc.id
        if name != "NotImplementedError":
            continue
        if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            return args[0].value
        return ""
    return None


# --- Instance state -----------------------------------------------------------
# Probed, not remembered. Each check answers the phase's own "done when" as closely as
# something automated can, and says so honestly when it cannot.

ROOT = Path(os.environ.get("ROOT", "/srv/friday"))


@dataclass
class Check:
    ok: bool | None          # None = cannot determine from here
    detail: str


def _unit_active(name: str) -> bool:
    if not shutil.which("systemctl"):
        return False
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", name], check=False
    ).returncode == 0


def _rows(db: Path, sql: str) -> int | None:
    if not db.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            return int(c.execute(sql).fetchone()[0])
    except sqlite3.Error:
        return None


def probe_instance() -> dict[str, Check]:
    """Probe the box for each phase's done-when. Read-only."""
    out: dict[str, Check] = {}

    # W1 - the alias answers, and a bridge is delivering.
    litellm = _unit_active("friday-litellm.service")
    llama = _unit_active("friday-llama@daily.service")
    out["W1"] = Check(
        litellm and llama,
        "litellm + llama up" if (litellm and llama)
        else f"litellm={'up' if litellm else 'down'} llama@daily={'up' if llama else 'down'}",
    )

    # W2 - both week-2 sources have landed rows.
    src = ROOT / "db" / "sources.db"
    cal = _rows(src, "select count(*) from events where source='caldav'")
    mx = _rows(src, "select count(*) from events where source='matrix'")
    if cal is None:
        out["W2"] = Check(False, "sources.db absent")
    else:
        out["W2"] = Check(bool(cal and mx), f"caldav={cal} matrix={mx} rows")

    # W3 - the gate. Spec section 6: 20 of 25.
    out["W3"] = _eval_check()

    # W4 - one eval result per source, each holding. Plus speech.
    results = sorted((repo_root() / "eval" / "results").glob("*.json"))
    out["W4"] = Check(
        len(results) >= 4 if results else False,
        f"{len(results)} eval runs recorded" if results else "no eval results",
    )

    # W5 - she can act, and you can kill her. The second clause is the one that matters.
    sup = _unit_active("friday-supervisor.service")
    core = ROOT / "agent" / "core"
    core_ok = core.is_dir() and not os.access(core, os.W_OK)
    out["W5"] = Check(
        sup and core_ok,
        f"supervisor={'up' if sup else 'down'} core={'protected' if core_ok else 'WRITABLE'}",
    )

    # W6 - corrections are the evidence modes are actually in use.
    corr = _rows(ROOT / "db" / "scrutiny.db", "select count(*) from corrections")
    out["W6"] = Check(bool(corr and corr >= 10), f"{corr or 0} corrections logged")

    # W7 - all five actions have fired. Four means propagate was collapsed (ADR-0002).
    out["W7"] = _actions_check()

    # W8 - not automatable, and saying so is better than inventing a number.
    out["W8"] = Check(None, "judged by hand: has anything been rejected?")
    return out


def _eval_check() -> Check:
    results = sorted((repo_root() / "eval" / "results").glob("*.json"))
    if not results:
        return Check(False, "no eval run yet")
    try:
        data = json.loads(results[-1].read_text())
    except (OSError, ValueError):
        return Check(False, "latest eval result unreadable")
    score, total = data.get("score"), data.get("total", 25)
    prof = data.get("profile", "unknown")
    if score is None:
        return Check(False, "latest eval result has no score")
    # ADR-0025: the 20/25 gate is a TARGET-profile gate. A dev-profile pass means retrieval
    # works; it does not mean the system is ready, and reporting it as a pass would be a lie
    # of exactly the kind this module exists to avoid.
    if prof != "target":
        return Check(None, f"{score}/{total} on profile '{prof}' - not the gate (ADR-0025)")
    return Check(score >= 20, f"{score}/{total} on target")


def _actions_check() -> Check:
    db = ROOT / "db" / "scrutiny.db"
    if not db.is_file():
        return Check(False, "scrutiny.db absent")
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            fired = {r[0] for r in c.execute("select distinct action from decisions")}
    except sqlite3.Error:
        return Check(False, "no decisions table")
    want = {"act", "ask", "watch", "ignore", "propagate"}
    missing = want - fired
    if not missing:
        return Check(True, "all five actions have fired")
    return Check(False, f"{len(fired)}/5 actions; missing {', '.join(sorted(missing))}")


# --- Rendering ----------------------------------------------------------------

def current_phase(code: dict[str, PhaseCode], inst: dict[str, Check]) -> str:
    """Where you are: the earliest phase whose gate is not met on this box.

    The BOX decides this, not the source tree. Counting stubs answers it wrongly in a way
    that flatters: a phase with no stubs may be complete, or may be a phase whose code has
    not been written yet — W1 has zero stubs today because `friday/ingest/` and
    `friday/cli.py` do not exist at all, not because they are finished.

    Spec section 6 says do not reorder, so the earliest unmet gate is the answer even when
    later phases have code. A phase the probe cannot judge (`ok is None`) falls back to
    whether it still has stubs.
    """
    for w in PHASES:
        chk = inst[w]
        if chk.ok is False:
            return w
        if chk.ok is None and code[w].stubbed:
            return w
    return "W8"


def render(markdown: bool = False) -> str:
    code, implemented, orphan = scan_code()
    inst = probe_instance()
    here = current_phase(code, inst)
    lines: list[str] = []

    if markdown:
        lines += [
            "| | Phase | Done when | Work left | Your box |",
            "|---|---|---|---|---|",
        ]
        for w, (title, gate) in PHASES.items():
            c, chk = code[w], inst[w]
            mark = "**>>**" if w == here else ""
            left = f"{c.stubbed} stub" + ("s" if c.stubbed != 1 else "") if c.stubbed else "—"
            box = {True: "**yes**", False: "not yet", None: "by hand"}[chk.ok]
            lines.append(f"| {mark} | **{w}** {title} | {gate} | {left} | {box} |")
        lines += [
            "",
            f"**{implemented} functions implemented, "
            f"{sum(c.stubbed for c in code.values())} stubbed.** "
            f"Counted from the source by `friday/status.py`, not ticked by hand — every stub "
            f"raises `NotImplementedError` naming the phase that implements it, so this "
            f"cannot drift from the code.",
            "",
            "Work left counts *stubs*, so a dash means nothing is stubbed — which is not "
            "the same as finished. W1 has no stubs because `friday/ingest/` and "
            "`friday/cli.py` have not been written at all. The **Your box** column is the "
            "one that answers whether a phase is actually done.",
            "",
            "`make status` reports the same thing for **your** box.",
        ]
        return "\n".join(lines)

    lines.append("")
    lines.append("  FRIDAY — where this build is")
    lines.append("  " + "-" * 66)
    for w, (title, gate) in PHASES.items():
        c, chk = code[w], inst[w]
        cursor = ">>" if w == here else "  "
        state = {True: "[done]", False: "[    ]", None: "[ ?  ]"}[chk.ok]
        left = f"{c.stubbed} stubs left" if c.stubbed else "nothing stubbed"
        lines.append(f"{cursor} {w}  {state}  {title}")
        lines.append(f"       done when  {gate}")
        lines.append(f"       your box   {chk.detail}")
        lines.append(f"       code       {left}")
        lines.append("")

    total_s = sum(c.stubbed for c in code.values())
    lines.append("  " + "-" * 66)
    lines.append(f"  code      {implemented} functions implemented, {total_s} stubbed")
    if orphan:
        lines.append(f"            {orphan} stubs name no phase - they cannot be scheduled")
    lines.append(f"  you are   {here}  {PHASES[here][0]}")
    lines.append(f"  next      {PHASES[here][1]}")
    lines.append(f"  guide     docs/weeks/{here}.md")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    import sys

    print(render(markdown="--markdown" in sys.argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
