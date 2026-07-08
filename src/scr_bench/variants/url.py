"""URL variant: web_search + web_fetch + run_bash, like a real coding agent.

We expose all three tools and let the model choose its retrieval path. web_search
and web_fetch are server-side (Anthropic-hosted); run_bash is client-side, so we
run a manual tool-use loop: while stop_reason is `tool_use`, dispatch each
client-side block, append a tool_result, re-invoke. Sum usage across every turn.

Per-turn tool selection is captured because the analysis depends on which path
the model took — fetch-the-tree vs search-then-grep vs raw-bash.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import anthropic

from ..config import Config
from ..tools import bash_sandbox

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a schema identification assistant. Given a JSON data sample, \
identify which schema in scope best describes it.

Rules:
1. If exactly one schema in scope matches all the sample's fields, name it
   and report its identifier.
2. If multiple schemas in scope could match, list them as candidates and
   explain why the input is ambiguous. Do not pick one silently.
3. If no schema in scope matches, say so plainly. Do not invent a schema.
4. If the sample mixes fields from multiple distinct schemas, flag the
   inconsistency and name both candidates.

Always cite the source path or identifier you used to ground your answer.
Prefer under-claiming to over-claiming."""


# Hard cap on the tool-use loop, just so a misbehaving run can't burn the budget.
MAX_TURNS = 25


# Server-side tool names per the latest GA spec; match the SDK 0.97 type aliases.
TOOLS_URL: list[dict[str, Any]] = [
    {"type": "web_search_20250305", "name": "web_search"},
    {"type": "web_fetch_20250910", "name": "web_fetch"},
    {
        "name": "run_bash",
        "description": (
            "Run a read-only bash command on the user's machine. Use for curl, "
            "grep, head, or `python -c` against fetched JSON. No filesystem "
            "writes (rm/mv/redirects are blocked) and no destructive ops. "
            "stdout is capped at 64KB. `jq` is NOT installed — use "
            "`python -c \"import json,sys;...\"` to filter JSON instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to run.",
                },
            },
            "required": ["command"],
        },
    },
]


def _build_prompt(sample_payload: Any, cfg: Config) -> str:
    repos = "\n".join(f"- {url}" for url in cfg.sources.url)
    return (
        "Identify the appropriate schema for the following sample. The schemas\n"
        "are published in these repositories:\n"
        "\n"
        f"{repos}\n"
        "\n"
        "Use whichever tools you find appropriate to ground your answer.\n"
        "\n"
        "Sample:\n"
        f"{json.dumps(sample_payload, indent=2)}"
    )


def _accepts_temperature(model_alias: str) -> bool:
    """Opus 4.7 removed sampling parameters; older models accept them."""
    return not model_alias.startswith("claude-opus-4-7")


def _content_to_param(content: list[Any]) -> list[dict[str, Any]]:
    """Convert a response's `content` (typed blocks) into the param shape we
    need to echo back as the assistant turn.

    The SDK accepts the typed objects directly when echoed, but serializing to
    plain dicts keeps the audit trail and lets us drop into json without
    SDK-version-specific helpers.
    """
    out: list[dict[str, Any]] = []
    for block in content:
        d = block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block)
        out.append(d)
    return out


def _format_tool_uses(content: list[Any]) -> list[dict[str, Any]]:
    """Pull every tool-use-style block (server- or client-side) for per-turn
    audit. We record name + a short input preview, not full inputs (some
    web_search inputs can be long)."""
    uses = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype not in {"tool_use", "server_tool_use", "mcp_tool_use"}:
            continue
        inp = getattr(block, "input", None)
        preview = ""
        if isinstance(inp, dict):
            # Show the most-distinctive field for each tool type
            for key in ("command", "url", "query"):
                if key in inp and isinstance(inp[key], str):
                    preview = inp[key][:200]
                    break
        uses.append({
            "type": btype,
            "name": getattr(block, "name", None),
            "id": getattr(block, "id", None),
            "input_preview": preview,
        })
    return uses


def run(
    *,
    client: anthropic.Anthropic,
    cfg: Config,
    sample: dict[str, Any],
    model_alias: str,
) -> dict[str, Any]:
    """Execute one URL variant request via a manual tool-use loop.

    Returns aggregated metrics + the final assistant text + a per-turn audit
    log of which tools were called.
    """
    prompt = _build_prompt(sample["payload"], cfg)

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    base_kwargs: dict[str, Any] = {
        "model": model_alias,
        "max_tokens": cfg.max_tokens,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "tools": TOOLS_URL,
    }
    if _accepts_temperature(model_alias):
        base_kwargs["temperature"] = cfg.temperature

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_creation = 0
    tool_calls = 0
    tools_used: set[str] = set()
    per_turn_tools: list[list[dict[str, Any]]] = []
    final_text_parts: list[str] = []
    final_response: Any = None
    stop_reason: str | None = None
    turns = 0

    t0 = time.monotonic()

    for _ in range(MAX_TURNS):
        response = client.messages.create(messages=messages, **base_kwargs)
        turns += 1
        final_response = response

        usage = response.usage
        total_input += usage.input_tokens
        total_output += usage.output_tokens
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        total_cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0

        per_turn_tools.append(_format_tool_uses(response.content))
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype in {"tool_use", "server_tool_use", "mcp_tool_use"}:
                tool_calls += 1
                name = getattr(block, "name", None)
                if name:
                    tools_used.add(name)
            if btype == "text":
                # We collect text from every turn — a server-side fetch may
                # interleave preamble text with later final text.
                pass

        stop_reason = response.stop_reason

        if stop_reason == "end_turn":
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    final_text_parts.append(block.text)
            break

        if stop_reason == "pause_turn":
            # Server-side iteration cap — re-send the assistant turn so the
            # API can resume the server-side loop.
            messages.append({"role": "assistant", "content": _content_to_param(response.content)})
            continue

        if stop_reason == "tool_use":
            # Client-side tool requested. Append assistant turn, run each
            # tool_use block, append a tool_result for each.
            messages.append({"role": "assistant", "content": _content_to_param(response.content)})
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == "run_bash":
                    cmd = (block.input or {}).get("command", "")
                    logger.info("run_bash: %s", cmd[:200])
                    result = bash_sandbox.run(cmd, timeout=30.0)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.format_for_model(),
                        "is_error": result.exit_code != 0,
                    })
                else:
                    # Unknown client-side tool; surface as an error result so
                    # the model can recover.
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"unknown client-side tool: {block.name}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # Anything else (max_tokens, refusal, etc.) — collect text and bail.
        for block in response.content:
            if getattr(block, "type", None) == "text":
                final_text_parts.append(block.text)
        break
    else:
        logger.warning("URL variant hit MAX_TURNS=%d without end_turn", MAX_TURNS)

    wall = time.monotonic() - t0

    # Best-effort serialization of the LAST response. The full per-turn responses
    # are reconstructable from the manifest's `messages` echo if we ever need them.
    raw_response: Any
    if final_response is not None and hasattr(final_response, "model_dump"):
        try:
            raw_response = final_response.model_dump(mode="json")
        except TypeError:
            raw_response = final_response.model_dump()
    else:
        raw_response = None

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_read_input_tokens": total_cache_read,
        "cache_creation_input_tokens": total_cache_creation,
        "tool_calls": tool_calls,
        "tools_used": sorted(tools_used),
        "turns": turns,
        "wall_seconds": wall,
        "stop_reason": stop_reason,
        "final_text": "".join(final_text_parts),
        "model_resolved": getattr(final_response, "model", model_alias),
        "raw_response": raw_response,
        # URL-variant-specific audit: per-turn tool selection.
        "per_turn_tools": per_turn_tools,
    }
