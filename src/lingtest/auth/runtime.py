"""Runtime application of reviewed authentication plans and trusted hooks."""

from __future__ import annotations

import base64
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
    """Create a client and apply a reviewed auth plan before downstream API cases."""

    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
    if plan is None or plan.kind in {"none", "custom_hook"}:
        return client
    if plan.kind == "unknown":
        client.close()
        raise ValueError("Authentication plan is unknown; resolve auth details before testing")
    try:
        _check_required_env(plan)
    except Exception:
        client.close()
        raise
    if plan.kind == "basic":
        try:
            username = _read_env(plan.username_env or "LINGTEST_BASIC_USERNAME")
            password = _read_env(plan.password_env or "LINGTEST_BASIC_PASSWORD")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            client.headers["Authorization"] = f"Basic {encoded}"
        except Exception:
            client.close()
            raise
        return client
    if plan.kind == "api_key":
        if not plan.apply:
            client.close()
            raise ValueError("API key plan is missing its application location")
        try:
            token = _read_env(plan.token_env or "LINGTEST_API_KEY")
            _apply_token(client, plan.apply.model_dump(), token)
        except Exception:
            client.close()
            raise
        return client
    if plan.login is None:
        if plan.kind in {"bearer", "cookie"}:
            if not plan.apply and plan.kind == "bearer":
                client.close()
                raise ValueError("Bearer plan is missing its header template")
            try:
                token = _read_env(plan.token_env or _default_token_env(plan.kind))
                if plan.apply:
                    _apply_token(client, plan.apply.model_dump(), token)
                elif plan.kind == "cookie":
                    raise ValueError("Cookie token plan is missing its cookie name")
            except Exception:
                client.close()
                raise
            return client
        client.close()
        raise ValueError("Authentication plan is missing login details")
    try:
        body = {name: _resolve_env(value) for name, value in plan.login.body.items()}
        request_args = {plan.login.content_type: body}
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


def _check_required_env(plan: AuthPlan) -> None:
    missing = [name for name in plan.required_env if not os.environ.get(name)]
    if missing:
        raise ValueError(
            "Required authentication environment variables are not set: " + ", ".join(missing)
        )


def _read_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise ValueError(f"Required authentication environment variable {name} is not set")
    return value


def _default_token_env(kind: str) -> str:
    return "LINGTEST_COOKIE_VALUE" if kind == "cookie" else "LINGTEST_BEARER_TOKEN"


def _apply_token(client: httpx.Client, application: dict[str, Any], token: str) -> None:
    template = application.get("template") or "{token}"
    value = template.format(token=token)
    if application.get("header"):
        client.headers[application["header"]] = value
    elif application.get("query_name"):
        client.params = {**dict(client.params), application["query_name"]: value}
    elif application.get("cookie_name"):
        client.cookies.set(application["cookie_name"], value)
    else:
        raise ValueError("Authentication plan has no header, query, or cookie application location")


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
