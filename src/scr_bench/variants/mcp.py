"""MCP variant: pass `mcp_servers` to the API; the server handles the tool-use loop.

`response.usage` covers the full server-side multi-turn cost, so one client API
call is sufficient. We still walk content blocks to count `mcp_tool_use`
invocations and capture which tools the model actually called.
"""
from __future__ import annotations

import json
import time
from typing import Any

import anthropic

from ..config import Config


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

# MCP connector beta header for client.beta.messages.create with mcp_servers.
MCP_BETA_HEADER = "mcp-client-2025-11-20"

# Label for the MCP server entry; referenced by the mcp_toolset entry in tools.
MCP_SERVER_NAME = "graph"


def _build_prompt(sample_payload: Any, cfg: Config) -> str:
    return (
        "Identify the appropriate schema for the following sample using the\n"
        "graph MCP server. Use the project content summary and node fetch tools\n"
        "to ground your answer; cite the matching node IDs.\n"
        "\n"
        f"project_id: {cfg.mcp_project_id}\n"
        "\n"
        "Sample:\n"
        f"{json.dumps(sample_payload, indent=2)}"
    )


def _accepts_temperature(model_alias: str) -> bool:
    """Opus 4.7 removed sampling parameters (temperature/top_p/top_k); they 400.
    Older models still accept temperature."""
    return not model_alias.startswith("claude-opus-4-7")


def _content_to_param(content: list[Any]) -> list[dict[str, Any]]:
    """Serialize response content blocks into the param shape required to echo
    them back as an assistant turn (used on pause_turn resume)."""
    out: list[dict[str, Any]] = []
    for block in content:
        d = block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block)
        out.append(d)
    return out


def _dump_response(response: Any) -> Any:
    """Best-effort serialization of the SDK response object for the audit log."""
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump(mode="json")
        except TypeError:
            return response.model_dump()
    if hasattr(response, "to_dict"):
        return response.to_dict()
    if hasattr(response, "dict"):
        return response.dict()
    return str(response)


def run(
    *,
    client: anthropic.Anthropic,
    cfg: Config,
    sample: dict[str, Any],
    model_alias: str,
) -> dict[str, Any]:
    """Execute one MCP variant request.

    Raises `anthropic.APIError` on hard API failures; the caller decides
    retry / persist policy.
    """
    prompt = _build_prompt(sample["payload"], cfg)

    create_kwargs: dict[str, Any] = {
        "model": model_alias,
        "max_tokens": cfg.max_tokens,
        # Cache the system prompt — it's identical across every run in this variant.
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": prompt}],
        "mcp_servers": [
            {
                "type": "url",
                "url": cfg.mcp_server_url,
                "name": MCP_SERVER_NAME,
                # The connector forwards this to the MCP server as the
                # `Authorization: Bearer <token>` header — that is how the
                # server authenticates the request.
                "authorization_token": cfg.mcp_token,
            }
        ],
        # The API requires every mcp_servers entry to be referenced by an
        # mcp_toolset entry in tools (added in the mcp-client-2025-11-20 beta).
        "tools": [
            {"type": "mcp_toolset", "mcp_server_name": MCP_SERVER_NAME},
        ],
        # Force one tool call per turn. The MCP connector appears to assign
        # colliding JSON-RPC ids to *parallel* tool calls, which drops one
        # response and stalls it ~300s; serializing tool use side-steps that.
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        "betas": [MCP_BETA_HEADER],
    }
    if _accepts_temperature(model_alias):
        create_kwargs["temperature"] = cfg.temperature

    # The API normally completes the MCP server-side tool-use loop in a single
    # response. But the loop has its own iteration cap (~10 turns), and chatty
    # models can hit it. When that happens the API returns
    # stop_reason="pause_turn" and we re-send the accumulated assistant content
    # to resume.
    messages: list[Any] = list(create_kwargs["messages"])
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_creation = 0
    tool_calls = 0
    tools_used: set[str] = set()
    final_text_parts: list[str] = []
    final_response: Any = None
    stop_reason: str | None = None
    turns = 0
    MAX_PAUSE_RESUMES = 3

    t0 = time.monotonic()
    for _ in range(MAX_PAUSE_RESUMES + 1):
        response = client.beta.messages.create(**{**create_kwargs, "messages": messages})
        turns += 1
        final_response = response

        usage = response.usage
        total_input += usage.input_tokens
        total_output += usage.output_tokens
        total_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        total_cache_creation += getattr(usage, "cache_creation_input_tokens", 0) or 0

        for block in response.content:
            btype = getattr(block, "type", None)
            if btype in {"mcp_tool_use", "tool_use", "server_tool_use"}:
                tool_calls += 1
                name = getattr(block, "name", None)
                if name:
                    tools_used.add(name)

        stop_reason = response.stop_reason
        if stop_reason == "pause_turn":
            # Append the assistant turn verbatim so the server can resume.
            messages = list(messages) + [
                {"role": "assistant", "content": _content_to_param(response.content)}
            ]
            continue

        # end_turn / max_tokens / refusal / etc. — collect text and finish.
        for block in response.content:
            if getattr(block, "type", None) == "text":
                final_text_parts.append(block.text)
        break
    wall = time.monotonic() - t0

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
        "raw_response": _dump_response(final_response) if final_response is not None else None,
    }
