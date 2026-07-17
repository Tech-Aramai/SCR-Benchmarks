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
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Known Git-for-Windows install locations, tried when `bash` isn't on PATH.
# Ordered most-common first.
_WINDOWS_BASH_FALLBACKS: tuple[str, ...] = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)

_bash_path: str | None = None


def _resolve_bash() -> str:
    """Locate a real bash executable and cache it.

    Raises RuntimeError if none can be found. This is deliberate: if bash is
    missing, the model's read-only tool calls all fail, and (left unchecked) the
    model quietly answers the schema-identification task from parametric memory
    while the harness still records a graded `ok` result — a silent data-integrity
    failure we hit in July 2026. Failing loudly turns that into a visible
    `status: error` (or an aborted run) instead of fabricated data.
    """
    global _bash_path
    if _bash_path is not None:
        return _bash_path
    found = shutil.which("bash")
    if found is None:
        for cand in _WINDOWS_BASH_FALLBACKS:
            if Path(cand).exists():
                found = cand
                break
    if found is None:
        raise RuntimeError(
            "bash executable not found on PATH or in known Git-for-Windows "
            "locations. The ZIP variant needs a real bash to read the local "
            "schema files. Install Git (Windows: git-scm.com) or add its bin/ to "
            "PATH, then re-run. Refusing to proceed so results are not silently "
            "fabricated from model memory."
        )
    _bash_path = found
    return _bash_path


def ensure_available() -> str:
    """Preflight check: resolve bash now (raising if absent) so a run aborts
    before spending API calls rather than erroring cell-by-cell. Returns the
    resolved path."""
    return _resolve_bash()

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
    # Resolve bash here (raises if missing) so a broken environment fails loudly
    # rather than returning an error the model papers over with a memory guess.
    bash = _resolve_bash()
    try:
        proc = subprocess.run(
            [bash, "-c", command],
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
