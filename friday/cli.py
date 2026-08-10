"""FRIDAY CLI. Typer entry point.

Week 1-2: `ask` only. Later weeks add `status`, `agents`, `eval`, `voice enroll`.

    uv run python -m friday.cli ask "what's my week look like"
    uv run python -m friday.cli status
    uv run python -m friday.cli agents
"""

from __future__ import annotations

import sys

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:
    # Allow the module to import without typer/rich for minimal environments.
    typer = None  # type: ignore[assignment]
    Console = None  # type: ignore[assignment,misc]

from friday.config import ConfigError, get

app = typer.Typer(no_args_is_help=True) if typer else None
console = Console() if Console else None


def _print(msg: str) -> None:
    if console:
        console.print(msg)
    else:
        print(msg)


@app.command() if typer else lambda f: f
def ask(question: str) -> None:
    """Ask FRIDAY something. Routes through the retrieval pipeline and the model.

    In W1-2 this is a simple LiteLLM call with injected temporal context.
    In W3+ it goes through the full retrieval pipeline first.
    """
    from friday.temporal import inject_context

    try:
        cfg = get()
    except ConfigError as exc:
        _print(f"[red]CONFIG ERROR[/red]\n{exc}")
        raise typer.Exit(1) if typer else sys.exit(1)

    context = inject_context()
    _print(f"[dim]{context}[/dim]\n")

    # Try the retrieval pipeline (W3+), fall back to direct model call (W1).
    try:
        from friday.memory.retrieve import build_context, retrieve
        from friday.temporal import now as _now

        results = retrieve(question, _now())
        if results:
            ctx = build_context(results, _now())
            _print(f"[dim]Retrieved {len(results)} chunks[/dim]\n")
        else:
            ctx = ""
    except (NotImplementedError, Exception):
        ctx = ""

    # Call the model through LiteLLM.
    try:
        import openai

        client = openai.OpenAI(
            base_url=cfg.friday.models.litellm_base_url + "/v1",
            api_key="sk-friday-dev",  # dev mode: LiteLLM runs without auth
        )
        messages = [
            {"role": "system", "content": f"{context}\n{ctx}" if ctx else context},
            {"role": "user", "content": question},
        ]
        resp = client.chat.completions.create(
            model="daily",
            messages=messages,
            max_tokens=4000,
            temperature=0.7,
        )
        answer = resp.choices[0].message.content or "(no response)"
        _print(answer)
    except Exception as exc:
        _print(f"[yellow]Model unavailable: {exc}[/yellow]")
        _print("[dim]Is friday-litellm.service running? try: systemctl status friday-litellm[/dim]")


@app.command() if typer else lambda f: f
def status() -> None:
    """Show where this build is: phases, gates, and what's running."""
    from friday.status import render

    _print(render())


@app.command() if typer else lambda f: f
def agents() -> None:
    """List every configured agent, its model alias, budget, and tools."""
    try:
        cfg = get()
    except ConfigError as exc:
        _print(f"[red]CONFIG ERROR[/red]\n{exc}")
        raise typer.Exit(1) if typer else sys.exit(1)

    table = Table(title="FRIDAY Agents") if Table else None
    if table:
        table.add_column("Agent", style="cyan")
        table.add_column("Model", style="magenta")
        table.add_column("Max Tokens", justify="right")
        table.add_column("Wall Clock (s)", justify="right")
        table.add_column("Sensitivity")
        table.add_column("Can Write")
        table.add_column("Tools")

        for name, spec in sorted(cfg.agents.agents.items()):
            table.add_row(
                name,
                spec.model,
                str(spec.max_tokens),
                str(spec.wall_clock_s),
                spec.sensitivity.value,
                "yes" if spec.can_write else "no",
                ", ".join(spec.tools) or "(none)",
            )
        _print(table)
    else:
        for name, spec in sorted(cfg.agents.agents.items()):
            _print(f"  {name:<14} model={spec.model} tokens={spec.max_tokens} tools={spec.tools}")


@app.command() if typer else lambda f: f
def profile() -> None:
    """Show the active hardware profile and what each alias resolves to."""
    from friday.profile import main as _profile_main

    _profile_main([])


@app.command() if typer else lambda f: f
def preflight() -> None:
    """Run the preflight checks."""
    import subprocess

    from friday.config import repo_root

    result = subprocess.run(
        ["bash", "install/preflight.sh"],
        cwd=str(repo_root()),
    )
    raise typer.Exit(result.returncode) if typer else sys.exit(result.returncode)


@app.command() if typer else lambda f: f
def ingest(source: str = "") -> None:
    """Run ingestion. With no arg, polls all enabled sources. With a name, polls one."""
    from friday.ingest.base import poll_all

    if source:
        _print(f"[dim]Polling {source}...[/dim]")
        # TODO: single-source poll
    else:
        _print("[dim]Polling all enabled sources...[/dim]")

    counts = poll_all()
    for name, count in sorted(counts.items()):
        status_str = f"{count} events" if count >= 0 else "FAILED"
        _print(f"  {name:<20} {status_str}")


def main() -> int:
    if app:
        app()
        return 0
    # Fallback without typer
    if len(sys.argv) < 2:
        print("Usage: python -m friday.cli <command>")
        print("Commands: ask, status, agents, profile, preflight, ingest")
        return 1
    cmd = sys.argv[1]
    if cmd == "status":
        status()
    elif cmd == "agents":
        agents()
    elif cmd == "profile":
        profile()
    elif cmd == "ask" and len(sys.argv) > 2:
        ask(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
