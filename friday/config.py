"""Configuration loading, validated strictly.

`config/friday.toml` says it in its own header and it is the rule for every model in this
module: **an unknown key is a load error, not an ignored line.** A typo must not silently
grant an unbounded budget, and a renamed key must not silently revert a threshold to its
default. Every model here sets `extra="forbid"`.

Two more rules, both from the config files themselves:

- **Budgets have no defaults.** `config/agents.yaml`: "Every entry needs all seven fields. A
  missing one is a validation error, never a default: an agent with no budget is a bug, not
  an unlimited agent."
- **Sensitivity has no default.** ADR-0008, and `friday.models.Sensitivity` says why.

`config/scrutiny.yaml` is deliberately NOT parsed here. `scrutiny.policy.load_table` owns it,
because that package must be readable and auditable on its own, and because the restricted
expression grammar for `when:` belongs next to the evaluator that enforces it. This module
only reports where the file is.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from friday.models import Routing, Sensitivity


class ConfigError(Exception):
    """Raised when a configuration file is missing, malformed, or internally inconsistent.

    Fatal at startup by design. A service that starts with a half-understood config is worse
    than one that refuses to start, because the failure surfaces later as behaviour rather
    than as an error.
    """


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- config/friday.toml ------------------------------------------------------


class General(_Strict):
    principal: str
    timezone: str
    log_level: str = "info"
    # Logging full prompts logs retrieved vault content into the journal. Debug only, and
    # the journal is not encrypted at rest the way the vault is.
    debug_prompts: bool = False


class Paths(_Strict):
    root: Path
    vault: Path
    db: Path
    agent: Path
    core: Path
    loops: Path
    ingest: Path
    work: Path
    eval: Path
    logs: Path
    models: Path
    secrets: Path


class ConfigFiles(_Strict):
    scrutiny: Path
    agents: Path
    memory: Path
    sources: Path


class ModelsCfg(_Strict):
    litellm_base_url: str
    virtual_keys: Path

    @field_validator("litellm_base_url")
    @classmethod
    def _loopback(cls, v: str) -> str:
        # Spec section 8: "Bind LiteLLM to 127.0.0.1 only." Spec section 9: no port
        # forwarding. A base URL pointing off-box is not a configuration choice, it is the
        # whole premise of the system being wrong, so it fails here rather than at the first
        # request.
        if not (v.startswith("http://127.0.0.1") or v.startswith("http://localhost")):
            raise ValueError(
                f"litellm_base_url must be loopback, got {v!r}. Spec section 8 binds LiteLLM "
                "to 127.0.0.1 and spec section 9 forbids port forwarding."
            )
        return v


class Tracing(_Strict):
    enabled: bool = True
    host: str = "http://127.0.0.1:3000"
    sample_rate: float = 1.0


class BargeIn(_Strict):
    """ADR-0019. Two phases, two deadlines.

    Phase 1 is acoustic and has no model in it: VAD during playback pauses TTS inside
    `stop_latency_ms`. Phase 2 is semantic and cannot start until end of speech: the router
    classifies the utterance into one of six kinds and Python dispatches.

    Conflating the two is the mistake this class exists to keep visible.
    """

    enabled: bool = False
    stop_latency_ms: int = 200
    require_aec: bool = True
    resume_on_unaddressed: bool = True
    resume_timeout_s: int = 8
    classify_with: str = "router"
    confidence_low: float = 0.60
    ambiguity_action: str = "ask"
    suspend_to_checkpoint: bool = True
    require_speaker_match_to_redirect: bool = True

    @model_validator(mode="after")
    def _boundaries(self) -> BargeIn:
        if not self.enabled:
            return self
        if not self.require_aec:
            raise ValueError(
                "barge_in.require_aec is false. Without echo cancellation her own output "
                "re-enters the microphone and she interrupts herself, which is the failure "
                "that makes people abandon full-duplex. ADR-0019 makes this a hardware "
                "requirement, not a preference."
            )
        if self.ambiguity_action != "ask":
            raise ValueError(
                f"barge_in.ambiguity_action is {self.ambiguity_action!r}. ADR-0019: ambiguity "
                "resolves to `ask` and never to a guess. 'What about Thursday?' is ambiguous "
                "in the utterance, not in the model, and applying a wrong guess silently to "
                "the right task is the expensive failure."
            )
        if not self.require_speaker_match_to_redirect:
            raise ValueError(
                "an unverified speaker could redirect a task. Spec section 9 gates every "
                "voice command on the voiceprint, and an interruption is a command. Anyone "
                "may pause her; only you may change what she is doing."
            )
        if self.resume_on_unaddressed and self.resume_timeout_s <= 0:
            raise ValueError(
                "resume_timeout_s must be positive. A pause that never resumes is worse than "
                "no barge-in: she stops mid-sentence and never finishes."
            )
        return self


class Voice(_Strict):
    enabled: bool = False
    stt_model: str = "large-v3-turbo"
    tts_engine: str = "kokoro"
    wake_word: str = "friday"
    wake_threshold: float = 0.6
    clap_to_wake: bool = True
    clap_exit_phrase: str = "stand down"
    speaker_threshold: float = 0.75
    require_speaker_match: bool = True
    latency_budget_ms: int = 800
    barge_in: BargeIn = BargeIn()

    @model_validator(mode="after")
    def _exit_phrase_is_not_a_backchannel(self) -> Voice:
        # ADR-0019. "ok", "yeah", "right", "mm-hm" are backchannels: things people say to
        # signal they are listening, mid-sentence, without meaning anything by them. An exit
        # phrase that collides with one asks the classifier to resolve an ambiguity that is
        # in the word rather than in the model, and it will get it wrong in both directions.
        backchannels = {"ok", "okay", "yeah", "yep", "right", "sure", "mm-hm", "uh-huh", "got it"}
        if self.clap_exit_phrase.strip().lower() in backchannels:
            raise ValueError(
                f"clap_exit_phrase {self.clap_exit_phrase!r} is a common backchannel. Pick a "
                "phrase nobody says by reflex mid-sentence - 'stand down' is the default for "
                "that reason. ADR-0019."
            )
        return self

    @model_validator(mode="after")
    def _gate_is_real(self) -> Voice:
        # Spec section 5 and 9: the Resemblyzer gate is a security control, not an input
        # convenience. docs/weeks/W5.md names lowering this threshold until it stops being
        # annoying as the most likely way the property is deleted, so the floor is enforced
        # here rather than left to discipline. Re-enrol in the room you actually use.
        if self.require_speaker_match and self.speaker_threshold < 0.65:
            raise ValueError(
                f"speaker_threshold {self.speaker_threshold} is below 0.65, which accepts "
                "roughly anyone. If the gate rejects you, re-enrol with the microphone and "
                "at the distance you actually use (docs/weeks/W5.md step 2). Moving this "
                "number is not the fix."
            )
        return self


class Output(_Strict):
    ai_chosen_surface: bool = True
    surfaces: tuple[str, ...] = ("voice", "wall", "map", "image", "chart", "text")
    default_surface: str = "voice"

    @model_validator(mode="after")
    def _default_is_available(self) -> Output:
        if self.default_surface not in self.surfaces:
            raise ValueError(f"default_surface {self.default_surface!r} is not in surfaces")
        return self


class SupervisorCfg(_Strict):
    health_check_interval_s: int = 30
    failures_before_revert: int = 3
    known_good_requires_eval: bool = True
    managed_units: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _gate_holds(self) -> SupervisorCfg:
        # ADR-0009: the known-good tag advances only after a full eval pass. Without it,
        # "last-known-good" degrades to "last thing that started without crashing", and
        # reverting to it restores a system that boots and retrieves badly.
        if not self.known_good_requires_eval:
            raise ValueError(
                "known_good_requires_eval is false. ADR-0009 makes the eval pass the gate on "
                "the known-good tag, which is what stops the supervisor reverting to a "
                "commit that starts cleanly and retrieves badly. Supersede the ADR rather "
                "than flipping the flag."
            )
        for unit in self.managed_units:
            if not unit.startswith("friday-"):
                raise ValueError(
                    f"managed unit {unit!r} does not start with 'friday-'. The polkit rule in "
                    "install/01-users.sh grants fridaysup exactly friday-* and nothing else, "
                    "so this unit could be listed here and never actually managed."
                )
            if unit == "friday-supervisor.service":
                raise ValueError(
                    "the supervisor may not manage itself. install/01-users.sh excludes it "
                    "from the polkit rule so that nothing it supervises can stop it."
                )
        return self


class Budgets(_Strict):
    tokens_per_hour: int
    tokens_per_day: int
    concurrent_tasks: int
    warn_at: float = 0.80
    soft_stop_at: float = 0.95
    hard_kill_at: float = 1.00
    sigterm_grace_s: int = 10
    keep_branch_on_kill: bool = True
    revert_vault_on_kill: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> Budgets:
        if not self.warn_at < self.soft_stop_at <= self.hard_kill_at:
            raise ValueError("budgets must satisfy warn_at < soft_stop_at <= hard_kill_at")
        return self


class Modes(_Strict):
    enabled: bool = False
    default: str = "assist"
    available: tuple[str, ...] = ("assist", "brainstorm", "focus", "away")
    brainstorm_suppresses: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _known(self) -> Modes:
        if self.default not in self.available:
            raise ValueError(f"default mode {self.default!r} is not in available")
        valid = {"act", "ask", "watch", "ignore", "propagate"}
        unknown = set(self.brainstorm_suppresses) - valid
        if unknown:
            raise ValueError(
                f"brainstorm_suppresses names {sorted(unknown)}, which are not among the five "
                "actions. ADR-0002: exactly five, and this list is written in their "
                "vocabulary so that wiring it to scrutiny in week 7 is a deletion rather "
                "than a rewrite."
            )
        return self


class KillSwitch(_Strict):
    phone: bool = True
    gpio_button: bool = False
    gpio_pin: int = 0


class FridayToml(_Strict):
    general: General
    paths: Paths
    config: ConfigFiles
    models: ModelsCfg
    tracing: Tracing = Tracing()
    voice: Voice = Voice()
    output: Output = Output()
    supervisor: SupervisorCfg = SupervisorCfg()
    budgets: Budgets
    modes: Modes = Modes()
    kill_switch: KillSwitch = KillSwitch()


# --- config/agents.yaml ------------------------------------------------------


class ToolSpec(_Strict):
    writes: bool
    week: int | str
    notes: str | None = None
    # ADR-0010: matching is on tool name AND input pattern, not name alone. That is what
    # makes spec section 9's "shell on one branch" expressible rather than aspirational.
    # Populated in W5; absent means the tool is allowed on name alone, which is only
    # acceptable for read-only tools.
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    allow_cwd: str | None = None

    @model_validator(mode="after")
    def _writers_are_patterned(self) -> ToolSpec:
        if self.writes and not (self.deny or self.allow or self.allow_cwd):
            # Not an error: the patterns arrive in W5 and the catalog exists from W1. This
            # is checked and reported by `python -m friday.config --check` instead, so the
            # gap is visible without blocking weeks 1 through 4.
            object.__setattr__(self, "_unpatterned", True)
        return self


class AgentSpec(_Strict):
    """One agent. All seven fields required.

    `config/agents.yaml`: "Every entry needs all seven fields. A missing one is a validation
    error, never a default: an agent with no budget is a bug, not an unlimited agent."

    No field below has a default. That is the whole point of this class.
    """

    model: str
    tools: tuple[str, ...]
    max_tokens: int
    wall_clock_s: int
    temperature: float
    sensitivity: Routing
    can_write: bool

    @model_validator(mode="after")
    def _bounded(self) -> AgentSpec:
        if self.max_tokens <= 0 or self.wall_clock_s <= 0:
            raise ValueError(
                "max_tokens and wall_clock_s must be positive. Spec section 9: runaway loops "
                "are the default failure, not an edge case."
            )
        if self.can_write and not self.tools:
            raise ValueError("can_write with an empty tool list: nothing can perform the write")
        return self


class AgentsYaml(_Strict):
    version: int
    tool_catalog: dict[str, ToolSpec]
    agents: dict[str, AgentSpec]
    sensitivity_routing: dict[Sensitivity, Routing]

    @model_validator(mode="after")
    def _consistent(self) -> AgentsYaml:
        for name, spec in self.agents.items():
            unknown = set(spec.tools) - set(self.tool_catalog)
            if unknown:
                raise ValueError(
                    f"agent {name!r} lists tools not in tool_catalog: {sorted(unknown)}"
                )
            if not spec.can_write:
                writers = [t for t in spec.tools if self.tool_catalog[t].writes]
                if writers:
                    raise ValueError(
                        f"agent {name!r} has can_write false but holds writing tools "
                        f"{writers}. One of the two is wrong, and guessing which is how a "
                        "read-only specialist quietly gains a write path."
                    )

        # The narrow point the whole security model rests on. ADR-0006: the scorer is the
        # one place ingested text meets a model, and it has no tools, so instructions hidden
        # in an email have nothing to call. This is checked rather than trusted because it is
        # a one-line change to break and there is no symptom until it is exploited.
        scorer = self.agents.get("scorer")
        if scorer is None:
            raise ValueError("config/agents.yaml has no `scorer` entry")
        if scorer.tools:
            raise ValueError(
                f"the scorer has tools {list(scorer.tools)}. ADR-0006: it must have none. "
                "It is the one place ingested text reaches a model, and the empty tool list "
                "is the boundary - not the untrusted-content wrapping, which is mitigation."
            )
        if scorer.can_write:
            raise ValueError("the scorer must not write")

        # Spec section 8: those four classes resolve local by config, not by preference.
        for cls_ in (
            Sensitivity.VAULT,
            Sensitivity.HEALTH,
            Sensitivity.MESSAGES,
            Sensitivity.FINANCES,
        ):
            if self.sensitivity_routing.get(cls_) is not Routing.LOCAL_ONLY:
                raise ValueError(
                    f"sensitivity_routing[{cls_.value}] must be local_only. Spec section 8 and "
                    "ADR-0008: a more capable non-local model is refused, not preferred."
                )
        return self


# --- config/memory.yaml ------------------------------------------------------


class ProfileCfg(_Strict):
    path: Path
    max_tokens: int = 1500
    required: bool = True
    honcho_proposals: bool = True
    auto_apply_proposals: bool = False

    @model_validator(mode="after")
    def _hand_written(self) -> ProfileCfg:
        # Spec section 7 and section 11: tier 1 is hand-written, never generated. Honcho
        # proposes; you approve. A flag that applies proposals directly turns the seed
        # everything grows from into something the system writes about you.
        if self.auto_apply_proposals:
            raise ValueError(
                "auto_apply_proposals is true. Spec section 7: profile.md is hand-written and "
                "Honcho's proposals queue for your approval. It is tier 1 of four and it is "
                "not generated."
            )
        return self


class EpisodicCfg(_Strict):
    db: Path
    append_only: bool = True
    wal: bool = True
    archive_dir: Path

    @model_validator(mode="after")
    def _append_only(self) -> EpisodicCfg:
        # Spec section 7: tier 2 is "append-only, never edited, only compressed". Compression
        # rewrites into summary rows and archives the originals; it does not edit in place.
        if not self.append_only:
            raise ValueError("episodic.append_only is false. Spec section 7 says never edited.")
        return self


class VaultCfg(_Strict):
    path: Path
    dirs: tuple[str, ...] = ("daily", "projects", "people", "ideas")
    git: bool = True
    commit_per_run: bool = True


class IndexCfg(_Strict):
    qdrant_url: str
    collection: str
    fts_db: Path
    embed_alias: str = "embed"
    rerank_alias: str = "rerank"
    embed_dim: int
    chunk_tokens: int = 512
    chunk_overlap_tokens: int = 64


class AlwaysInject(_Strict):
    datetime: bool = True
    todays_calendar: bool = True


class RetrieveCfg(_Strict):
    """Spec section 7's pipeline, as parameters.

    expand query -> parallel keyword + vector (top 30 each) -> dedupe -> rerank to top 8 ->
    recency boost. The order is in `friday.memory.retrieve`; these are its constants.
    """

    expansions: int = 3
    keyword_k: int = 30
    vector_k: int = 30
    fusion: str = "rrf"
    rerank_to: int = 8
    recency_boost: bool = True
    recency_half_life_days: int = 30
    min_rerank_score: float = 0.15
    context_tokens: int = 6000
    always_inject: AlwaysInject = AlwaysInject()
    carry_provenance: bool = True
    stale_after_days: int = 90

    @model_validator(mode="after")
    def _spec_section_7(self) -> RetrieveCfg:
        if self.fusion != "rrf":
            raise ValueError(
                f"fusion {self.fusion!r}. config/memory.yaml: keyword and vector produce scores "
                "on incomparable scales, and normalising them is a knob that drifts silently."
            )
        if not self.always_inject.datetime:
            raise ValueError(
                "always_inject.datetime is false. Spec section 7: local models are hopeless at "
                "temporal reasoning otherwise. This is injected, not retrieved, because "
                "retrieval can miss and the date cannot be allowed to."
            )
        if not self.carry_provenance:
            raise ValueError(
                "carry_provenance is false. Spec section 7: always carry source and timestamp "
                "so she can say 'you told me this in March, it may be stale.'"
            )
        return self


class BoundedCfg(_Strict):
    """ADR-0007. Consolidate when full, not on a timer.

    Spec section 7: "when memory fills, the agent must consolidate before it can save
    anything new - is better than nightly compression. Scarcity forces curation."
    """

    enabled: bool = True
    max_live_events: int
    max_vault_notes: int
    soft_start_at: float = 0.85
    block_writes_when_full: bool = True
    scheduled_pass: str | None = "03:00"

    @model_validator(mode="after")
    def _still_bounded(self) -> BoundedCfg:
        # The exact reversion ADR-0007 was written against, and the one an earlier draft of
        # this scaffold made: a nightly compression job with an unbounded write path between
        # passes. It has no pressure in it, and retrieval degrades on a curve nobody watches.
        if self.enabled and not self.block_writes_when_full:
            raise ValueError(
                "block_writes_when_full is false. ADR-0007: the write path blocks, and that "
                "block IS the forcing function. A queue that grows while waiting is unbounded "
                "memory in a different file. `scheduled_pass` is allowed in addition and may "
                "not be the only consolidation."
            )
        if not 0.0 < self.soft_start_at < 1.0:
            raise ValueError("soft_start_at must be between 0 and 1 exclusive")
        return self


class EvalCfg(_Strict):
    questions: Path
    pass_threshold: int = 20
    total: int = 25
    results_dir: Path


class MemoryYaml(_Strict):
    version: int
    profile: ProfileCfg
    episodic: EpisodicCfg
    vault: VaultCfg
    index: IndexCfg
    retrieve: RetrieveCfg
    bounded: BoundedCfg
    eval: EvalCfg


# --- config/sources.yaml -----------------------------------------------------


class SourceDefaults(_Strict):
    enabled: bool = False
    poll_interval_s: int = 300
    sink: Path
    max_events_per_poll: int = 500
    tag_untrusted: bool = True


class SourceCfg(_Strict):
    module: str
    week: int
    enabled: bool = False
    poll_interval_s: int | None = None
    sensitivity: Sensitivity
    config: dict[str, Any] = Field(default_factory=dict)


class Retention(_Strict):
    sources_db_days: int = 30
    require_consolidated: bool = True
    require_indexed: bool = True

    @model_validator(mode="after")
    def _no_premature_prune(self) -> Retention:
        # config/sources.yaml: never prune a row that has not been consolidated AND indexed,
        # whatever its age. Pruning on age alone silently loses anything that arrived while
        # consolidation was behind.
        if not (self.require_consolidated and self.require_indexed):
            raise ValueError(
                "retention must require both consolidated and indexed before pruning. "
                "sources.db is a landing zone; the episodic log is the durable record, and a "
                "row that never reached it is not recoverable."
            )
        return self


class SourcesYaml(_Strict):
    version: int
    defaults: SourceDefaults
    sources: dict[str, SourceCfg]
    retention: Retention

    @model_validator(mode="after")
    def _tagged(self) -> SourcesYaml:
        # ADR-0006. Tagging is mitigation and not the boundary, and it is still not optional:
        # the boundary behind it (the scorer's empty tool list) is easier to reason about
        # when everything arriving is at least marked.
        if not self.defaults.tag_untrusted:
            raise ValueError(
                "defaults.tag_untrusted is false. Spec section 9: everything ingested gets "
                "wrapped and marked. It is mitigation, not a fix - see ADR-0006 for where the "
                "real boundary is - and it is still not optional."
            )
        return self

    def interval(self, name: str) -> int:
        src = self.sources[name]
        return src.poll_interval_s or self.defaults.poll_interval_s

    def enabled_for_week(self, week: int) -> list[str]:
        """Sources that should be live by the end of a given week. docs/weeks/W2, W4."""
        return sorted(n for n, s in self.sources.items() if s.week <= week)


# --- The aggregate -----------------------------------------------------------


class Config(_Strict):
    """Everything, loaded and cross-validated.

    `scrutiny` is a path and not a parsed table. `scrutiny.policy.load_table` owns that file
    so the triage layer stays auditable on its own.
    """

    repo: Path
    friday: FridayToml
    agents: AgentsYaml
    memory: MemoryYaml
    sources: SourcesYaml
    scrutiny_path: Path

    @model_validator(mode="after")
    def _cross(self) -> Config:
        paths = self.friday.paths
        if self.memory.vault.path != paths.vault:
            raise ValueError(
                f"memory.yaml vault.path {self.memory.vault.path} disagrees with friday.toml "
                f"paths.vault {paths.vault}"
            )
        if self.memory.profile.path != paths.vault / "profile.md":
            raise ValueError("memory.yaml profile.path is not vault/profile.md")
        if paths.core != paths.agent / "core":
            raise ValueError("paths.core must be paths.agent/core; ADR-0004 keys on that path")

        aliases = {a.model for a in self.agents.agents.values()}
        aliases |= {self.memory.index.embed_alias, self.memory.index.rerank_alias}
        if "fast" not in aliases:
            raise ValueError("no agent uses the `fast` alias; spec section 4 scores on the 4B router")
        return self

    def agent(self, name: str) -> AgentSpec:
        try:
            return self.agents.agents[name]
        except KeyError:
            raise ConfigError(
                f"no agent named {name!r} in config/agents.yaml. An agent without an entry has "
                "no budget and no allowlist, which is a bug rather than an unlimited agent."
            ) from None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def repo_root() -> Path:
    """The repository root, found from this file rather than from the cwd.

    Systemd units start with an arbitrary working directory, so anything relative to `.`
    resolves differently under a unit than it does in your shell, and that difference shows
    up as a missing config file at 3am rather than at development time.
    """
    return Path(__file__).resolve().parent.parent


def load(repo: Path | None = None) -> Config:
    """Load and cross-validate every configuration file.

    Raises:
        ConfigError: a file is missing, malformed, contains an unknown key, or contradicts
            another file. Never returns a partially-valid Config: spec section 9's budgets
            and ADR-0008's routing are only real if the file that declares them parsed.
    """
    root = (repo or repo_root()).resolve()
    toml_path = root / "config" / "friday.toml"
    if not toml_path.is_file():
        raise ConfigError(f"missing {toml_path}")

    try:
        raw = tomllib.loads(toml_path.read_text())
        friday = FridayToml.model_validate(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{toml_path}: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"{toml_path}: {exc}") from exc

    def _rel(p: Path) -> Path:
        return p if p.is_absolute() else root / p

    try:
        agents = AgentsYaml.model_validate(_read_yaml(_rel(friday.config.agents)))
        memory = MemoryYaml.model_validate(_read_yaml(_rel(friday.config.memory)))
        sources = SourcesYaml.model_validate(_read_yaml(_rel(friday.config.sources)))
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(str(exc)) from exc

    scrutiny_path = _rel(friday.config.scrutiny)
    if not scrutiny_path.is_file():
        raise ConfigError(f"missing {scrutiny_path}")

    try:
        return Config(
            repo=root,
            friday=friday,
            agents=agents,
            memory=memory,
            sources=sources,
            scrutiny_path=scrutiny_path,
        )
    except Exception as exc:
        raise ConfigError(str(exc)) from exc


@lru_cache(maxsize=1)
def get() -> Config:
    """Process-wide config. Loaded once, at first use, and never reloaded.

    Deliberately not hot-reloadable. A budget or a sensitivity route that changes underneath
    a running task means the task was admitted under one policy and is being killed under
    another. Restart the unit; the supervisor is watching and will notice either way.
    """
    return load()


def main() -> int:
    """`python -m friday.config --check`. Validates every file and reports.

    Called by install/04-services.sh before enabling anything, and worth running by hand
    after editing any config file. A config error found here costs a second; the same error
    found by a unit costs a journal read.
    """
    import sys

    try:
        cfg = load()
    except ConfigError as exc:
        print(f"CONFIG ERROR\n{exc}", file=sys.stderr)
        return 1

    print(f"repo          {cfg.repo}")
    print(f"principal     {cfg.friday.general.principal}  tz={cfg.friday.general.timezone}")
    print(f"agents        {len(cfg.agents.agents)}: {', '.join(sorted(cfg.agents.agents))}")
    print(f"sources       {len(cfg.sources.sources)}, live: "
          f"{', '.join(n for n, s in cfg.sources.sources.items() if s.enabled) or 'none'}")
    print(f"bounded       max_live_events={cfg.memory.bounded.max_live_events} "
          f"block_when_full={cfg.memory.bounded.block_writes_when_full}")
    print(f"scrutiny      {cfg.scrutiny_path} (parsed by scrutiny.policy.load_table)")

    if cfg.friday.general.timezone == "UTC":
        print(
            "\nWARN  timezone is still UTC. docs/weeks/W2.md: a wrong timezone makes every "
            "calendar answer wrong in a way that looks like a retrieval problem."
        )
    unpatterned = [
        n for n, t in cfg.agents.tool_catalog.items()
        if t.writes and not (t.deny or t.allow or t.allow_cwd)
    ]
    if unpatterned:
        print(
            f"\nWARN  writing tools with no input patterns: {', '.join(sorted(unpatterned))}. "
            "ADR-0010: matching on tool name alone cannot express 'shell on one branch'. "
            "Patterns arrive in week 5 (docs/weeks/W5.md step 5)."
        )
    print("\nconfig ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
