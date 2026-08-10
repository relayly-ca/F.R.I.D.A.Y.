"""The seven axes, and the scorer that produces them. Spec section 4.

The split this module exists to enforce: score.py MAY call a model. policy.py may not.
The model produces seven numbers; Python turns them into an action. Injected text can move
a number, and it cannot move a rule.

The scorer runs on `fast` (the 4B router) with `tools: []`. Both matter:

  - `fast`, because the whole economic argument for this layer is that it rejects
    low-value signals BEFORE the expensive model is invoked. Scoring on `daily` would
    make triage cost more than skipping triage.
  - `tools: []`, because this is the one place ingested text reaches a model. Instructions
    hidden in an email have nothing to call. ADR-0006.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

# Exactly these seven, in this order. Spec section 4. Adding or removing one is a schema
# change touching this module, config/scrutiny.yaml and the tests, and it needs an ADR.
AXES = (
    "urgency",
    "impact",
    "novelty",
    "risk",
    "confidence",
    "specificity",
    "conflict",
)


class ScoreError(Exception):
    """Raised when a model returns something that is not a valid score.

    Deliberately fatal rather than lenient. A scorer that silently substitutes defaults for
    a malformed response produces decisions that look principled and are not, and the
    threshold table cannot tell the difference.
    """


@dataclass(frozen=True)
class Score:
    """The seven axes for one signal.

    Six floats in 0.0-1.0 and one boolean. `conflict` is a boolean because a signal either
    contradicts something already recorded or it does not; a 0.4 conflict is not a thing.

    Frozen, because a decision must be reproducible from the score that produced it. If
    something mutated a Score after the fact, the correction ledger would record a score
    that never existed.
    """

    urgency: float
    impact: float
    novelty: float
    risk: float
    confidence: float
    specificity: float
    conflict: bool = False

    def __post_init__(self) -> None:
        for axis in AXES:
            value = getattr(self, axis)
            if axis == "conflict":
                if not isinstance(value, bool):
                    raise ScoreError(f"conflict must be a bool, got {type(value).__name__}")
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ScoreError(f"{axis} must be a number, got {type(value).__name__}")
            if not 0.0 <= float(value) <= 1.0:
                raise ScoreError(f"{axis} must be in 0.0-1.0, got {value}")

    def as_dict(self) -> dict[str, Any]:
        """The environment the rule table is evaluated against."""
        return asdict(self)


# The scorer prompt. The model returns ONLY a JSON object with the seven axes.
# `body` is already wrapped by the caller (friday.models.wrap_untrusted); the
# untrusted text never appears outside that wrapper in the prompt.
_SCORE_PROMPT = """\
You are a signal triage scorer. Score the following signal on seven axes.

Return ONLY a JSON object with exactly these keys and nothing else:
  urgency: float 0.0-1.0  — how soon this stops being actionable
  impact: float 0.0-1.0   — how much it matters if handled well or badly
  novelty: float 0.0-1.0  — is this new; something already known scores near zero
  risk: float 0.0-1.0    — cost of acting and being wrong
  confidence: float 0.0-1.0 — how sure you are of your read
  specificity: float 0.0-1.0 — how completely the action is already determined
  conflict: bool          — does this contradict something already recorded

Context (read-only, pre-computed by the caller):
{context_block}

Signal:
{body}

Return ONLY the JSON object. No prose, no explanation, no markdown fences.
"""


def _build_client():
    """Create an OpenAI client pointed at the local LiteLLM proxy.

    The openai client is the wire format to LiteLLM on loopback (http://127.0.0.1:4000/v1),
    not a cloud call. See pyproject.toml.
    """
    from openai import OpenAI

    return OpenAI(base_url="http://127.0.0.1:4000/v1", api_key="sk-scrutiny")


def score_signal(
    body: str,
    context: Mapping[str, Any] | None = None,
    *,
    client: Any = None,
) -> Score:
    """Score one signal on the seven axes. The only place ingested text meets a model.

    Contract:
      - Runs the `scorer` agent from config/agents.yaml: `fast`, tools [], temperature 0,
        400 tokens.
      - `body` is UNTRUSTED and is wrapped and marked before it reaches the prompt. That
        tagging is mitigation, not a fix (spec section 9) - the boundary is the empty tool
        list, not the wrapping.
      - Returns a Score. Never returns, suggests, or names an action. If a future prompt
        change makes the model emit an action, that is a bug even if the action is right.
      - `novelty` requires a retrieval lookup against the vault: something already recorded
        is not new however good it is. That lookup is read-only and pre-computed by the
        caller, arriving here as `context`.

    The ``client`` parameter is for testing: pass a mock/fake client to avoid a live
    model call. In production it defaults to a real OpenAI client at the LiteLLM proxy.

    Raises:
        ScoreError: the model returned a malformed or out-of-range score.

    Implemented in week 7. Spec section 6 puts Adaptive Scrutiny at week 7, after memory,
    voice and tools, because `novelty` is meaningless without a populated vault and
    `specificity` is hard to judge without the tool surface that would execute the action.
    """
    ctx = dict(context or {})
    context_block = json.dumps(ctx, default=str, indent=2) if ctx else "(none)"

    prompt = _SCORE_PROMPT.format(context_block=context_block, body=body)

    if client is None:
        client = _build_client()

    resp = client.chat.completions.create(
        model="fast",
        messages=[{"role": "user", "content": prompt}],
        tools=[],
        temperature=0,
        max_tokens=400,
    )
    raw = resp.choices[0].message.content
    if not raw:
        raise ScoreError("model returned an empty response")
    return parse_score(raw)


def parse_score(raw: str) -> Score:
    """Parse the model's JSON response into a Score.

    Strict. A missing axis, an extra axis, a value out of range or unparseable JSON all
    raise rather than being repaired. A repaired score is a guess wearing a number.
    """
    text = raw.strip()

    # Some models wrap JSON in markdown fences despite instructions not to.
    # Strip them if present, but do not repair structural problems inside the JSON.
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScoreError(f"model response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ScoreError(f"model response must be a JSON object, got {type(data).__name__}")

    # Exactly these seven keys, no more, no less.
    data_keys = set(data.keys())
    expected_keys = set(AXES)
    missing = expected_keys - data_keys
    extra = data_keys - expected_keys
    if missing:
        raise ScoreError(f"missing axes in score: {sorted(missing)}")
    if extra:
        raise ScoreError(f"unexpected axes in score: {sorted(extra)}")

    # Type and range validation per axis. No defaults, no coercion.
    kwargs: dict[str, Any] = {}
    for axis in AXES:
        value = data[axis]
        if axis == "conflict":
            if not isinstance(value, bool):
                raise ScoreError(
                    f"conflict must be a bool, got {type(value).__name__}: {value!r}"
                )
            kwargs[axis] = value
        else:
            # Reject bools masquerading as numbers (True/False are int subclasses).
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ScoreError(
                    f"{axis} must be a number, got {type(value).__name__}: {value!r}"
                )
            fval = float(value)
            if not 0.0 <= fval <= 1.0:
                raise ScoreError(f"{axis} must be in 0.0-1.0, got {fval}")
            kwargs[axis] = fval

    return Score(**kwargs)
