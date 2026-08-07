"""Hardware profiles. ADR-0025.

The same repository runs on the dev box and on the target box, and nothing in the
architecture depends on which. The mechanism is spec section 8's aliases: a profile changes
what `daily` POINTS AT and touches no calling code.

Three layers, and confusing them is the thing this docstring exists to prevent:

    config/agents.yaml     which ALIAS a task uses      - per task
    config/litellm.yaml    what an alias means          - the alias table
    config/profiles.yaml   what an alias means HERE     - per machine

A profile may change what runs. It may never change what is true: `config/profiles.yaml`
carries both lists, and `verify_constraints` below enforces the second one rather than
trusting it, because a profile that could relax a security property would be a way to
disable one by choosing a config file.

This module is also imported by install scripts through the venv, so it must not import
anything heavier than the config layer.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from friday.config import ConfigError, repo_root

PROFILE_FILE = "/etc/friday/profile"
DEFAULT_PROFILE = "target"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LlamaArgs(_Strict):
    ctx_size: int = 8192
    # Absent on dev, deliberately. llama.cpp falls back to CPU cleanly when this is unset;
    # forcing layers onto a card that cannot hold them fails at load with a message that
    # scrolls past in a unit's journal.
    n_gpu_layers: int | None = None


class Profile(_Strict):
    """One profile from config/profiles.yaml."""

    describe: str
    min_vram_mb: int
    min_disk_gb: int
    aliases: dict[str, str | None]
    resident: tuple[str, ...]
    voice_default: bool
    # Per-agent, per-box. Distinct from `aliases`, which is per-box only: "what does `daily`
    # mean here" and "does the consolidator specifically need something better here" are
    # different questions and collapsing them loses the second one.
    agent_overrides: dict[str, str] = {}
    llama_args: LlamaArgs = LlamaArgs()

    @model_validator(mode="after")
    def _coherent(self) -> Profile:
        for alias in self.resident:
            if alias not in self.aliases:
                raise ValueError(f"resident alias {alias!r} is not in this profile's alias map")
        for agent, alias in self.agent_overrides.items():
            if alias not in self.aliases:
                raise ValueError(
                    f"agent_overrides[{agent}] = {alias!r}, which this profile does not map. "
                    "An override names an alias, not a model."
                )
        return self

    def served(self) -> list[str]:
        """Aliases this profile actually serves. A null mapping means not served here."""
        return [a for a, m in self.aliases.items() if m]


class Profiles(_Strict):
    version: int
    default: str
    profiles: dict[str, Profile]
    constraints: dict[str, list[str]]
    eval: dict[str, Any]

    @model_validator(mode="after")
    def _default_exists(self) -> Profiles:
        if self.default not in self.profiles:
            raise ValueError(f"default profile {self.default!r} is not defined")
        return self


@lru_cache(maxsize=1)
def _load(repo: Path | None = None) -> Profiles:
    path = (repo or repo_root()) / "config" / "profiles.yaml"
    if not path.is_file():
        raise ConfigError(f"missing {path}")
    try:
        return Profiles.model_validate(yaml.safe_load(path.read_text()))
    except Exception as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def active_name() -> str:
    """The active profile name.

    Precedence: `FRIDAY_PROFILE`, then `/etc/friday/profile`, then `target`.

    The default is `target` on purpose. A forgotten setting must degrade toward the correct
    system rather than away from it: shipping the real box still on dev weights is a silent
    failure, while the reverse fails loudly at model load.
    """
    name = os.environ.get("FRIDAY_PROFILE", "").strip()
    if not name:
        try:
            name = Path(PROFILE_FILE).read_text().strip()
        except OSError:
            name = ""
    return name or DEFAULT_PROFILE


def active() -> Profile:
    """The active profile.

    Raises:
        ConfigError: the named profile is not defined. Deliberately fatal - a typo in
            /etc/friday/profile must not silently fall back to a different machine's model
            set, because the symptom is "why is it slow" three days later.
    """
    profiles = _load()
    name = active_name()
    try:
        return profiles.profiles[name]
    except KeyError:
        raise ConfigError(
            f"unknown profile {name!r}. config/profiles.yaml defines: "
            f"{', '.join(sorted(profiles.profiles))}"
        ) from None


def alias_for(agent: str) -> str:
    """The alias an agent resolves to under the active profile.

    Order: the agent's own `model` from config/agents.yaml, then this profile's
    `agent_overrides` if it names one. The override replaces the alias; it never replaces
    the agent's tools, budget or `can_write`, so a profile cannot widen what an agent may do.

    Raises:
        ConfigError: no such agent.
    """
    from friday.config import get

    spec = get().agent(agent)
    return active().agent_overrides.get(agent, spec.model)


def verify_constraints() -> list[str]:
    """Check that the active profile has not relaxed anything it may not.

    `config/profiles.yaml` lists what a profile may and may not change. The second list is
    the interesting one, and it is CHECKED rather than trusted: a profile that could turn off
    the scorer's empty tool list, or unpin sensitivity routing, would be a way to disable a
    security property by choosing a config file.

    Returns:
        Violations, empty if clean. Callers treat a non-empty result as fatal.

    Implemented in W1 alongside install/04-services.sh, which refuses to install units when
    this returns anything.
    """
    raise NotImplementedError(
        "friday.profile.verify_constraints is implemented in W1. It re-reads the invariants "
        "from config/agents.yaml and config/memory.yaml under the active profile and asserts "
        "each item in profiles.yaml `may_not_change` still holds."
    )


def render_litellm(out: Path) -> None:
    """Write the profile's LiteLLM config.

    `config/litellm.yaml` is the alias table. This resolves each alias through the profile
    and drops any the profile does not serve, so on dev nothing points at a port with no
    llama-server behind it.

    On dev, `daily` and `fast` resolve to the same model, so both `model_name` entries point
    at the same `api_base` and ONE llama-server serves both. That is the whole reason a
    profile can be cheap: no calling code learns about it.

    Implemented in W1.
    """
    raise NotImplementedError("friday.profile.render_litellm is implemented in W1")


def render_llama_env(out_dir: Path) -> list[Path]:
    """Write one env file per served alias for `friday-llama@.service`.

    Implemented in W1.
    """
    raise NotImplementedError("friday.profile.render_llama_env is implemented in W1")


def main() -> int:
    """`python -m friday.profile` - show the active profile and what it resolves to."""
    import sys

    try:
        prof, name = active(), active_name()
    except ConfigError as exc:
        print(f"PROFILE ERROR\n{exc}", file=sys.stderr)
        return 1

    print(f"profile       {name}")
    print(f"              {prof.describe.strip()}")
    print(f"vram floor    {prof.min_vram_mb} MB      disk floor {prof.min_disk_gb} GB")
    print(f"resident      {', '.join(prof.resident)}")
    print(f"voice         {'on' if prof.voice_default else 'off'} by default")
    print("\nalias -> model")
    for alias, model in prof.aliases.items():
        print(f"  {alias:<8} {model or '(not served on this profile)'}")

    try:
        from friday.config import get

        print("\nagent -> alias")
        for agent in sorted(get().agents.agents):
            resolved = alias_for(agent)
            override = " (override)" if agent in prof.agent_overrides else ""
            print(f"  {agent:<14} {resolved}{override}")
    except ConfigError as exc:
        print(f"\n(agents unavailable: {exc})")

    if name != "target":
        print(
            "\nNOTE  the 20/25 eval gate is a TARGET-profile gate (ADR-0025). Retrieval is "
            "comparable across profiles because embed and rerank are identical; answer "
            "quality is not."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
