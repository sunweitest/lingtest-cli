"""Explicit trust policy; models cannot elevate it."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlparse


class TrustMode(StrEnum):
    GUARDED = "guarded"
    TRUSTED_PROJECT = "trusted-project"
    FULL = "full"


REVIEW_ACTIONS = {"review_functional", "review_api", "review_auth"}


def parse_trust_mode(value: str | TrustMode | None) -> TrustMode:
    try:
        return TrustMode(value or TrustMode.GUARDED)
    except ValueError as exc:
        choices = ", ".join(mode.value for mode in TrustMode)
        raise ValueError(f"Unknown trust mode {value!r}; use {choices}") from exc


def requires_approval(
    mode: str | TrustMode,
    action: str,
    *,
    target_url: str | None = None,
    allowed_hosts: set[str] | None = None,
    dangerous_methods: set[str] | None = None,
) -> bool:
    """Return whether an action needs a human interrupt."""

    trust = parse_trust_mode(mode)
    if trust is TrustMode.FULL:
        return False
    if action in REVIEW_ACTIONS:
        return True
    if trust is TrustMode.GUARDED:
        return True
    if action == "write_script":
        return False
    if action == "run_tests":
        host = (urlparse(target_url).hostname or "").lower() if target_url else ""
        allowlist = {item.lower() for item in allowed_hosts or set()}
        if not host or host not in allowlist:
            return True
        return bool(dangerous_methods)
    return True


def assert_non_negotiable_scope(
    *,
    project_root: str,
    target_path: str,
) -> None:
    """Keep file writes within the project even in full trust mode."""

    from pathlib import Path

    root = Path(project_root).resolve()
    target = Path(target_path)
    resolved = (root / target).resolve() if not target.is_absolute() else target.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"Output path escapes the trusted project: {target_path}")
