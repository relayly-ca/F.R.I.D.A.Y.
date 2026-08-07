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
from friday.models import Sensitivity

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
    CHECKED rather than trusted: a profile that could turn off the scorer's empty tool list,
    or unpin sensitivity routing, would be a way to disable a security property by choosing a
    config file. `install/04-services.sh` refuses to install any unit when this returns
    anything.

    Note what this deliberately does NOT do: it does not read the `may_not_change` list and
    interpret it. That list is prose for a human. Each invariant below is asserted directly
    against the live configuration, because a check driven by a string in the same file it is
    checking can be disabled by editing that string.

    Returns:
        Violations, empty if clean.
    """
    from friday.config import ConfigError, get

    out: list[str] = []
    try:
        cfg = get()
    except ConfigError as exc:
        return [f"configuration does not load: {exc}"]

    prof = active()

    # ADR-0006. The one place ingested text meets a model, and the empty tool list is the
    # boundary - not the untrusted-content wrapping, which is mitigation.
    scorer = cfg.agents.agents.get("scorer")
    if scorer is None:
        out.append("no `scorer` agent in config/agents.yaml")
    else:
        if scorer.tools:
            out.append(f"scorer has tools {list(scorer.tools)}; ADR-0006 requires none")
        if scorer.can_write:
            out.append("scorer has can_write true; it must never write")

    # ADR-0008. Four classes pin local, by config and not by preference.
    for cls in ("vault", "health", "messages", "finances"):
        routed = cfg.agents.sensitivity_routing.get(Sensitivity(cls))
        if routed is None or routed.value != "local_only":
            out.append(f"sensitivity_routing[{cls}] is {routed}; ADR-0008 requires local_only")

    # Spec section 9. Every agent bounded, and an override may not have widened one.
    for name, spec in cfg.agents.agents.items():
        if spec.max_tokens <= 0 or spec.wall_clock_s <= 0:
            out.append(f"agent {name} has a non-positive budget")
        if name in prof.agent_overrides:
            # An override names an ALIAS. If it ever grew the ability to name tools or
            # can_write, a profile would become a way to widen an agent's permissions.
            if not isinstance(prof.agent_overrides[name], str):
                out.append(f"agent_overrides[{name}] is not an alias name")

    # ADR-0007. The write path blocks; a queue is unbounded memory in a different file.
    bounded = cfg.memory.bounded
    if bounded.enabled and not bounded.block_writes_when_full:
        out.append("memory bound does not block writes; ADR-0007 requires it")

    # ADR-0004. The path the filesystem boundary is keyed on.
    if cfg.friday.paths.core != cfg.friday.paths.agent / "core":
        out.append("paths.core is not paths.agent/core; ADR-0004 keys on that path")

    # ADR-0009.
    if not cfg.friday.supervisor.known_good_requires_eval:
        out.append("known_good_requires_eval is false; ADR-0009 requires it")

    # Spec section 8 and 9: loopback only.
    base = cfg.friday.models.litellm_base_url
    if not (base.startswith("http://127.0.0.1") or base.startswith("http://localhost")):
        out.append(f"litellm_base_url {base} is not loopback")

    # ADR-0019, when the gate is on at all.
    voice = cfg.friday.voice
    if voice.require_speaker_match and voice.speaker_threshold < 0.65:
        out.append(f"speaker_threshold {voice.speaker_threshold} is below the 0.65 floor")

    # A profile may only serve aliases that config/litellm.yaml knows about, or nothing
    # points at a port with no server behind it.
    for alias in prof.served():
        if alias not in _litellm_aliases():
            out.append(f"profile serves alias {alias!r}, absent from config/litellm.yaml")

    return out


def _litellm_aliases(repo: Path | None = None) -> dict[str, dict[str, Any]]:
    """The alias table from config/litellm.yaml, keyed by `model_name`."""
    path = (repo or repo_root()) / "config" / "litellm.yaml"
    if not path.is_file():
        raise ConfigError(f"missing {path}")
    data = yaml.safe_load(path.read_text()) or {}
    out: dict[str, dict[str, Any]] = {}
    for entry in data.get("model_list", []):
        name = entry.get("model_name")
        if name:
            out[name] = entry
    return out


def render_litellm(out: Path) -> None:
    """Write the profile's LiteLLM config.

    `config/litellm.yaml` is the alias table and stays the source. This resolves each alias
    through the active profile, drops any the profile does not serve, and rewrites `api_base`
    so two aliases backed by the same model share one llama-server.

    That last part is the whole reason a profile is cheap. On dev, `daily` and `fast` both
    resolve to the small model, so both `model_name` entries point at port 8080 and ONE
    server answers both. Nothing in `friday/` learns about it: callers still ask for `daily`.

    Fallbacks are pruned to aliases that survive. A fallback pointing at an unserved alias
    turns a recoverable failure into a confusing one.
    """
    prof = active()
    table = _litellm_aliases()
    served = prof.served()

    # model -> the port of the first alias serving it. Deterministic ordering, because a
    # rendered config that changes between runs makes a diff useless for spotting drift.
    port_for_model: dict[str, str] = {}
    entries: list[dict[str, Any]] = []

    for alias in served:
        model = prof.aliases[alias]
        assert model is not None  # served() filtered these
        src = table.get(alias)
        if src is None:
            raise ConfigError(
                f"profile serves alias {alias!r}, which config/litellm.yaml does not define"
            )
        entry = yaml.safe_load(yaml.safe_dump(src))  # deep copy through the same loader
        api_base = port_for_model.get(model)
        if api_base is None:
            api_base = entry["litellm_params"]["api_base"]
            port_for_model[model] = api_base
        entry["litellm_params"]["api_base"] = api_base
        entry["litellm_params"]["model"] = f"openai/{model}"
        entries.append(entry)

    raw = yaml.safe_load(((repo_root()) / "config" / "litellm.yaml").read_text()) or {}
    rendered: dict[str, Any] = {"model_list": entries}

    router = dict(raw.get("router_settings") or {})
    fallbacks = []
    for fb in router.get("fallbacks") or []:
        pruned = {k: [t for t in v if t in served] for k, v in fb.items() if k in served}
        pruned = {k: v for k, v in pruned.items() if v}
        if pruned:
            fallbacks.append(pruned)
    if fallbacks:
        router["fallbacks"] = fallbacks
    else:
        router.pop("fallbacks", None)
    if router:
        rendered["router_settings"] = router

    for key in ("litellm_settings", "general_settings"):
        if raw.get(key):
            rendered[key] = raw[key]

    header = (
        "# GENERATED by friday.profile.render_litellm. Do not edit.\n"
        f"# profile: {active_name()}\n"
        "# Source of truth is config/litellm.yaml; edit that and re-run\n"
        "# install/04-services.sh.\n"
    )
    out.write_text(header + yaml.safe_dump(rendered, sort_keys=False))


def render_llama_env(out_dir: Path) -> list[Path]:
    """Write one env file per served alias for `friday-llama@.service`.

    One file per *alias*, not per model. Two aliases backed by the same model on dev would
    otherwise both want the same port, and systemd would start two servers racing for it.
    Aliases after the first for a given model are skipped: they share the port, and
    `render_litellm` points them at it.

    Returns the files written.
    """
    prof = active()
    table = _litellm_aliases()
    written: list[Path] = []
    seen_models: set[str] = set()

    out_dir.mkdir(parents=True, exist_ok=True)
    for alias in prof.served():
        model = prof.aliases[alias]
        assert model is not None
        if model in seen_models:
            continue
        seen_models.add(model)

        api_base = table[alias]["litellm_params"]["api_base"]
        port = api_base.rstrip("/").rsplit(":", 1)[-1].split("/")[0]

        args = [f"--ctx-size {prof.llama_args.ctx_size}"]
        if prof.llama_args.n_gpu_layers is not None:
            args.append(f"--n-gpu-layers {prof.llama_args.n_gpu_layers}")
        # Retrieval models are not chat models and llama-server needs telling.
        if alias == "embed":
            args += ["--embedding", "--pooling cls"]
        elif alias == "rerank":
            args.append("--reranking")
        args.append(f"--alias {model}")

        path = out_dir / f"{alias}.env"
        path.write_text(
            f"# GENERATED by friday.profile.render_llama_env. Do not edit.\n"
            f"# profile: {active_name()}   alias: {alias}\n"
            f"MODEL=/srv/friday/models/{model}.gguf\n"
            f"PORT={port}\n"
            f"ARGS={' '.join(args)}\n"
        )
        written.append(path)
    return written


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
