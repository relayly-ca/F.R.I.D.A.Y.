"""The checker. ADR-0013: the writer is never the checker.

W3 documents the failure this exists for - "the digest is confidently wrong" - and why a
better prompt does not fix it: a model grading its own output inflates its confidence,
reliably, and the consolidator has just spent its entire context deciding the note was right.

So a DIFFERENT agent asks one narrow question: does every claim in this note appear in the
rows it was built from. Quality is bounded by that schema rather than by model size, which is
the same argument config/agents.yaml already makes for the consolidator running on `fast`.

A note that fails goes to the inbox rather than to disk. It is not silently dropped - a
consolidation that quietly discards its output is indistinguishable from one that had nothing
to say.

Implemented in W3.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from friday.config import get

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    unsupported: tuple[str, ...] = ()
    reason: str = ""


# The checker agent name in config/agents.yaml. Must differ from the writer.
_CHECKER_AGENT = "curator"
_WRITER_AGENT = "consolidator"


def _get_openai_client():
    from openai import OpenAI

    cfg = get()
    base_url = cfg.friday.models.litellm_base_url
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return OpenAI(base_url=base_url, api_key="sk-friday-internal")


def check_note(note: str, sources: list[str], writer_agent: str) -> CheckResult:
    """Check a generated note against the rows it was built from.

    Args:
        writer_agent: The agent that produced the note. Passed so this function can REFUSE to
            check using the same agent. That refusal is the whole point of the module;
            leaving it to a config value makes it a setting rather than an invariant.

    Raises:
        ValueError: the configured checker agent equals `writer_agent`.
    """
    # ADR-0013: the writer is never the checker. This is an invariant, not a setting.
    if writer_agent == _CHECKER_AGENT:
        raise ValueError(
            f"check_note refuses to check using {writer_agent!r}, the same agent that "
            f"wrote the note. ADR-0013: the writer is never the checker - a model grading "
            f"its own output inflates its confidence, reliably, and the consolidator has "
            f"just spent its entire context deciding the note was right."
        )

    if not sources:
        return CheckResult(
            ok=False,
            reason="no source rows provided; cannot verify any claim",
        )

    cfg = get()
    checker_model = cfg.agent(_CHECKER_AGENT).model

    # Build the check prompt: narrow, single question
    sources_text = "\n---\n".join(sources)
    prompt = (
        "You are a fact-checker. You are given a note and the source rows it was built from. "
        "Your job is to answer ONE question: does every claim in the note appear in the "
        "source rows?\n\n"
        "Respond as JSON with exactly these keys:\n"
        '  {"ok": true/false, "unsupported": ["claim 1", ...], "reason": "..."}\n\n'
        "Rules:\n"
        "- A claim is supported if it appears in or is directly entailed by the sources.\n"
        "- A claim that is not supported goes in `unsupported`.\n"
        "- ok is true only if `unsupported` is empty.\n"
        "- Do not add information not present in the sources.\n\n"
        f"SOURCE ROWS:\n{sources_text}\n\n"
        f"NOTE TO CHECK:\n{note}\n"
    )

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=checker_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.0,
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        return CheckResult(
            ok=bool(result.get("ok", False)),
            unsupported=tuple(result.get("unsupported", [])),
            reason=str(result.get("reason", "")),
        )
    except Exception as e:
        logger.error("check_note failed: %s", e)
        # On any failure, fail safe: don't write the note
        return CheckResult(
            ok=False,
            reason=f"checker error: {e}",
        )
