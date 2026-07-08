"""Sandboxed bash executor for the URL and ZIP variants.

Conventionally read-only: a per-variant denylist screens the raw command string
against a regex set before we hand it to bash. We use `bash -c` (not `shell=True`)
so the executable is the same on POSIX and Windows-with-bash, and so cmd.exe
isn't accidentally invoked on Windows.

Hardening here is best-effort — the threat model is "the model emits something
silly", not "an adversary is trying to break out". Output is capped, the
command is timeout-bounded, and destructive verbs / write redirects are rejected.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Patterns rejected for every variant. \b is a word boundary so "remove" doesn't
# match `\brm\b`. `>>?` matches both `>` and `>>` redirects. Backticks are blocked
# because they're command substitution that bypasses our screen; `$(...)` is
# allowed because legit jq/python pipelines need it and the substituted command
# still runs through bash under our denylist.
_COMMON_DENY = (
    r"\brm\b",
    r"\bmv\b",
    r"\bsudo\b",
    r"\bkill\b",
    r"\bdd\b",
    r"\bchmod\b",
    r"\bchown\b",
    r">>?",      # > and >>
    r"`",        # backtick command substitution
)


@dataclass(frozen=True)
class BashResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool

    def format_for_model(self) -> str:
        parts = [f"exit_code: {self.exit_code}"]
        if self.stdout:
            parts.append(f"stdout:\n{self.stdout}")
        if self.stderr:
            parts.append(f"stderr:\n{self.stderr}")
        if self.truncated:
            parts.append("(stdout truncated)")
        return "\n".join(parts)


def run(
    command: str,
    *,
    extra_deny: tuple[str, ...] = (),
    cwd: Path | None = None,
    timeout: float = 30.0,
    max_stdout: int = 64 * 1024,
) -> BashResult:
    patterns = _COMMON_DENY + extra_deny
    for p in patterns:
        if re.search(p, command):
            return BashResult(
                stdout="",
                stderr=f"command rejected by sandbox (matched /{p}/)",
                exit_code=126,
                truncated=False,
            )
    try:
        proc = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired:
        return BashResult(
            stdout="",
            stderr=f"command exceeded {timeout}s timeout",
            exit_code=124,
            truncated=False,
        )
    except FileNotFoundError as e:
        return BashResult(
            stdout="",
            stderr=f"bash not on PATH: {e}",
            exit_code=127,
            truncated=False,
        )

    stdout = proc.stdout or ""
    full_len = len(stdout)
    truncated = full_len > max_stdout
    if truncated:
        stdout = stdout[:max_stdout] + f"\n... [truncated; total {full_len} bytes]"
    return BashResult(
        stdout=stdout,
        stderr=proc.stderr or "",
        exit_code=proc.returncode,
        truncated=truncated,
    )
