"""Authentication plan extraction from OpenAPI and human-readable auth documentation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lingtest.ai.prompts import AUTH_PLAN_SYSTEM
from lingtest.ai.structured import request_structured
from lingtest.auth.models import AuthPlan, AuthPlanDraft
from lingtest.document_loader import read_document
from lingtest.openapi import load_spec

_SECRET_FIELD = re.compile(
    r"password|passwd|client[_-]?secret|secret|access[_-]?token|refresh[_-]?token|"
    r"token|api[_-]?key|credential|username|user_name|email",
    re.I,
)
_ENV_REF = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)}$")
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)((?:\"|')?\b(?:password|passwd|client[_-]?secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|token|secret|username|email|user[_-]?id)"
    r"\b(?:\"|')?\s*[:=]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;]+)"
)
_DOCUMENTED_ENV_VALUE = re.compile(r"^(['\"]?)\$\{[A-Z][A-Z0-9_]*\}\1$")
_VALID_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BEARER_LITERAL = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{16,}={0,2}")
_URL_CREDENTIALS = re.compile(
    r"(?i)(\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^:/@\s]+:)" r"[^@/\s]+(@)"
)


def create_auth_plan(
    source: str | Path,
    *,
    auth_document: str | Path | None = None,
    provider=None,
    project_root: str | Path | None = None,
) -> AuthPlan:
    """Create a deterministic plan from OpenAPI or extract one from auth docs with an LLM.

    An OpenAPI-only plan never calls a provider. Supplying an auth document invokes structured
    extraction so human docs can explain details OpenAPI usually omits (test account role, login
    fields, or token response shape). The model receives redacted text and no credential values.
    """

    source_path = Path(source)
    auth_path = Path(auth_document) if auth_document else None
    openapi_path = source_path if source_path.suffix.lower() in {".json", ".yaml", ".yml"} else None
    if openapi_path is None and auth_path is None:
        auth_path = source_path

    if auth_path is None:
        plan = _plan_from_openapi(openapi_path, project_root=project_root)
        if plan is None:
            raise ValueError(
                "No supported OpenAPI authentication scheme found; provide an auth document "
                "with --auth-doc"
            )
        return plan

    if provider is None:
        raise ValueError("Auth documentation extraction requires an LLM provider")
    auth_text = read_document(auth_path)
    sanitized_auth = _redact_auth_text(auth_text)
    openapi_context = _auth_context(openapi_path) if openapi_path else ""
    messages = [
        {"role": "system", "content": AUTH_PLAN_SYSTEM},
        {
            "role": "user",
            "content": (
                "Extract a reviewable auth plan from these sources.\n\n"
                f"OpenAPI authentication metadata:\n{openapi_context or '(not supplied)'}\n\n"
                f"Authentication documentation (secret values redacted):\n{sanitized_auth}"
            ),
        },
    ]
    draft = request_structured(provider, messages, AuthPlanDraft)
    draft = _sanitize_draft(draft)
    root = Path(project_root or Path.cwd()).resolve()
    paths = [path.resolve() for path in (openapi_path, auth_path) if path]
    labels = [
        str(path.relative_to(root)).replace("\\", "/")
        if path == root or root in path.parents
        else path.name
        for path in paths
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return AuthPlan(
        **draft.model_dump(),
        source=" + ".join(labels),
        source_sha256=digest.hexdigest(),
    )


def _plan_from_openapi(path: Path | None, *, project_root: str | Path | None) -> AuthPlan | None:
    if path is None:
        return None
    from lingtest.auth.openapi import analyze_openapi_auth

    return analyze_openapi_auth(path, project_root=project_root)


def _auth_context(path: Path | None) -> str:
    if path is None:
        return ""
    spec = load_spec(path)
    context = {
        "security": spec.get("security"),
        "securitySchemes": spec.get("components", {}).get("securitySchemes", {}),
        "x-lingtest-auth": spec.get("x-lingtest-auth"),
    }
    return _redact_auth_text(json.dumps(context, ensure_ascii=False, indent=2))[:20_000]


def _redact_auth_text(text: str) -> str:
    def redact(match: re.Match[str]) -> str:
        value = match.group(2)
        if _DOCUMENTED_ENV_VALUE.fullmatch(value):
            return match.group(0)
        return match.group(1) + "[REDACTED]"

    cleaned = _SECRET_ASSIGNMENT.sub(redact, text)
    cleaned = _BEARER_LITERAL.sub(r"\1[REDACTED]", cleaned)
    return _URL_CREDENTIALS.sub(r"\1[REDACTED]\2", cleaned)


def _sanitize_draft(draft: AuthPlanDraft) -> AuthPlanDraft:
    """Replace secret-looking literals and derive the env list without exposing values."""

    warnings = [_redact_auth_text(item) for item in draft.warnings]
    required = set(draft.required_env)
    login = draft.login
    if login is not None:
        body = dict(login.body)
        for name, value in body.items():
            match = _ENV_REF.fullmatch(value)
            if match:
                required.add(match.group(1))
            elif _SECRET_FIELD.search(name):
                env_name = _env_name(name)
                body[name] = "${" + env_name + "}"
                required.add(env_name)
                warnings.append(
                    f"Replaced a literal value for sensitive field {name!r} with an "
                    "environment reference."
                )
        login = login.model_copy(update={"body": body})

    token_env = _safe_env_name(draft.token_env, "LINGTEST_BEARER_TOKEN", warnings)
    username_env = _safe_env_name(draft.username_env, "LINGTEST_USERNAME", warnings)
    password_env = _safe_env_name(draft.password_env, "LINGTEST_PASSWORD", warnings)
    for name in (token_env, username_env, password_env):
        if name:
            required.add(name)

    valid_required = sorted(name for name in required if _VALID_ENV_NAME.fullmatch(name))
    if len(valid_required) != len(required):
        warnings.append("Removed an invalid environment-variable name from required_env.")

    application = draft.apply
    if application and application.template:
        allowed_templates = {"{token}", "Bearer {token}"}
        if application.template not in allowed_templates:
            application = application.model_copy(update={"template": "{token}"})
            warnings.append("Replaced an unrecognized auth template with the token placeholder.")

    return draft.model_copy(
        update={
            "login": login,
            "apply": application,
            "token_env": token_env,
            "username_env": username_env,
            "password_env": password_env,
            "required_env": valid_required,
            "warnings": warnings,
        }
    )


def _safe_env_name(value: str | None, fallback: str, warnings: list[str]) -> str | None:
    if value is None:
        return None
    if _VALID_ENV_NAME.fullmatch(value):
        return value
    warnings.append(f"Replaced an invalid environment-variable name with {fallback}.")
    return fallback


def _env_name(field: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", field).strip("_").upper()
    return "LINGTEST_" + (normalized or "SECRET")
