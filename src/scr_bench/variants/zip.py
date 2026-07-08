"""ZIP variant: model reads schemas off local disk via a sandboxed run_bash.

Schemas are pre-extracted into the corpus's fixtures/zip/ before the run
(out-of-band, see README). The bash sandbox is rooted there and blocks network egress
so the only retrieval surface is the local filesystem.

Same manual tool-use loop shape as the URL variant — different toolset and a
different prompt. We don't refactor a shared helper yet because the divergence
between url and zip is small and explicit; if a fourth variant arrives it'll
be time to extract.
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


MAX_TURNS = 25

# Block network egress (curl/wget/etc.) on top of the destructive-ops denylist
# in bash_sandbox._COMMON_DENY. The model only has the local filesystem.
ZIP_EXTRA_DENY: tuple[str, ...] = (
    r"\bcurl\b",
    r"\bwget\b",
    r"\bnc\b",
    r"\bssh\b",
    r"\bftp\b",
    r"\bscp\b",
)


TOOLS_ZIP: list[dict[str, Any]] = [
    {
        "name": "run_bash",
        "description": (
            "Run a read-only bash command rooted at the extracted-schema "
            "directory (your current working directory). Use for "
            "ls, cat, grep, find, head, or `python -c` against the JSON files. "
            "No network access (curl/wget blocked). No filesystem writes "
            "(rm/mv/redirects blocked). stdout is capped at 64KB. `jq` is NOT "
            "installed — use `python -c \"import json,sys;...\"` to filter "
            "JSON instead."
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
    }
]


def _build_prompt(sample_payload: Any, cfg: Config) -> str:
    listing = "\n".join(f"- {z.dir}/  ({z.label})" for z in cfg.sources.zip)
    return (
        "Identify the appropriate schema for the following sample. The candidate\n"
        "schemas are JSON files reachable from your run_bash working directory,\n"
        "which contains these extracted schema sets:\n"
        "\n"
        f"{listing}\n"
        "\n"
        "Use the run_bash tool to list and read these files.\n"
        "\n"
        "Sample:\n"
        f"{json.dumps(sample_payload, indent=2)}"
    )


def _accepts_temperature(model_alias: str) -> bool:
    return not model_alias.startswith("claude-opus-4-7")


def _content_to_param(content: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in content:
        d = block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block)
        out.append(d)
    return out


def _format_tool_uses(content: list[Any]) -> list[dict[str, Any]]:
    uses = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype not in {"tool_use", "server_tool_use"}:
            continue
        inp = getattr(block, "input", None)
        preview = ""
        if isinstance(inp, dict):
            cmd = inp.get("command")
            if isinstance(cmd, str):
                preview = cmd[:200]
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
    """Execute one ZIP variant request via the manual tool-use loop."""
    zip_root = cfg.zip_root
    if not zip_root.exists():
        raise RuntimeError(
            f"ZIP fixtures directory missing: {zip_root.resolve()}. "
            f"Extract {cfg.schemas_zip_dir}/*.zip into {zip_root}/ first (see README)."
        )

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
        "tools": TOOLS_ZIP,
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
            if btype in {"tool_use", "server_tool_use"}:
                tool_calls += 1
                name = getattr(block, "name", None)
                if name:
                    tools_used.add(name)

        stop_reason = response.stop_reason

        if stop_reason == "end_turn":
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    final_text_parts.append(block.text)
            break

        if stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": _content_to_param(response.content)})
            continue

        if stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": _content_to_param(response.content)})
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == "run_bash":
                    cmd = (block.input or {}).get("command", "")
                    logger.info("run_bash: %s", cmd[:200])
                    result = bash_sandbox.run(
                        cmd,
                        extra_deny=ZIP_EXTRA_DENY,
                        cwd=zip_root,
                        timeout=30.0,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.format_for_model(),
                        "is_error": result.exit_code != 0,
                    })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"unknown client-side tool: {block.name}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        for block in response.content:
            if getattr(block, "type", None) == "text":
                final_text_parts.append(block.text)
        break
    else:
        logger.warning("ZIP variant hit MAX_TURNS=%d without end_turn", MAX_TURNS)

    wall = time.monotonic() - t0

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
        "per_turn_tools": per_turn_tools,
    }
