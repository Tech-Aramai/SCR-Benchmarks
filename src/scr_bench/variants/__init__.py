"""Variant runners.

Each variant exposes `run(*, client, cfg, sample, model_alias) -> dict` returning
token usage, final text, tool-call counts, and the raw response payload for audit.
"""
