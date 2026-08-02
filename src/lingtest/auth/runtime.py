"""Runtime application of reviewed authentication plans and trusted hooks."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from lingtest.auth.models import AuthHook, AuthPlan


def build_authenticated_client(
    base_url: str,
    *,
    timeout: float,
    plan: AuthPlan | None = None,
) -> httpx.Client:
    """Create a client and apply a reviewed bearer or cookie login plan."""

    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
    if plan is None or plan.kind in {"none", "unknown", "custom_hook"}:
        return client
    if plan.login is None:
        client.close()
        raise ValueError("Authentication plan is missing login details")
    body = {name: _resolve_env(value) for name, value in plan.login.body.items()}
    request_args = {plan.login.content_type: body}
    try:
        response = client.request(plan.login.method, plan.login.path, **request_args)
        response.raise_for_status()
        if plan.kind == "bearer":
            if (
                not plan.extract
                or not plan.extract.json_path
                or not plan.apply
                or not plan.apply.header
            ):
                raise ValueError("Bearer authentication plan is incomplete")
            token = _read_json_path(response.json(), plan.extract.json_path)
            template = plan.apply.template or "Bearer {token}"
            client.headers[plan.apply.header] = template.format(token=token)
    except Exception:
        client.close()
        raise
    return client


def load_auth_hook(
    hook: AuthHook,
    *,
    project_root: str | Path | None = None,
) -> Callable[[httpx.Request], None]:
    """Load an explicitly approved hook after checking its review digest."""

    root = Path(project_root or Path.cwd()).resolve()
    path = Path(hook.path)
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("Authentication hook must remain inside the project")
    source = resolved.read_bytes()
    if hashlib.sha256(source).hexdigest() != hook.sha256:
        raise ValueError("Authentication hook changed after approval; review it again")
    spec = importlib.util.spec_from_file_location("lingtest_runtime_auth_hook", resolved)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load authentication hook: {resolved}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    callback = getattr(module, hook.function, None)
    if not callable(callback):
        raise ValueError(f"Authentication hook function {hook.function!r} is not callable")
    return callback


def _resolve_env(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return os.environ[value[2:-1]]
    return value


def _read_json_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Token JSON path {path!r} was not found")
        current = current[part]
    return current
