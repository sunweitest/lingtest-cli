"""Build secret-free authentication plans from OpenAPI security metadata."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from lingtest.auth.models import (
    AuthApplication,
    AuthPlan,
    LoginRequest,
    TokenExtraction,
)
from lingtest.openapi import load_spec


def analyze_openapi_auth(
    path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> AuthPlan | None:
    """Infer common auth transports and OAuth2 token acquisition from an OpenAPI file.

    Only a small, documented subset is automated. Unsupported interactive flows return a plan
    requiring a pre-issued token rather than attempting browser login or guessing credentials.
    """

    source_path = Path(path)
    spec = load_spec(source_path)
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source = _display_path(source_path, project_root)

    extension = spec.get("x-lingtest-auth")
    if extension is not None:
        if not isinstance(extension, dict):
            raise ValueError("OpenAPI x-lingtest-auth must be an object")
        return _from_extension(extension, source=source, source_hash=source_hash)

    scheme_name, scheme, alternatives = _selected_scheme(spec)
    if scheme is None:
        if scheme_name is not None:
            return _plan(
                kind="unknown",
                confidence="low",
                warnings=[
                    f"OpenAPI security requirement {scheme_name!r} cannot be represented by "
                    "one supported auth plan."
                ],
                source=source,
                source_hash=source_hash,
            )
        return None

    warnings: list[str] = []
    if alternatives:
        warnings.append(
            f"OpenAPI declares alternative auth schemes; selected {scheme_name!r}. Review the plan."
        )

    scheme_type = str(scheme.get("type", "")).lower()
    if scheme_type == "http":
        http_scheme = str(scheme.get("scheme", "")).lower()
        if http_scheme == "bearer":
            env_name = "LINGTEST_BEARER_TOKEN"
            return _plan(
                kind="bearer",
                apply=AuthApplication(
                    header="Authorization",
                    template="Bearer {token}",
                ),
                token_env=env_name,
                required_env=[env_name],
                confidence="high",
                warnings=[
                    "OpenAPI defines Bearer transport but no token acquisition flow; "
                    "provide a pre-issued test token."
                ],
                source=source,
                source_hash=source_hash,
            )
        if http_scheme == "basic":
            username_env = "LINGTEST_BASIC_USERNAME"
            password_env = "LINGTEST_BASIC_PASSWORD"
            return _plan(
                kind="basic",
                username_env=username_env,
                password_env=password_env,
                required_env=[username_env, password_env],
                confidence="high",
                warnings=warnings,
                source=source,
                source_hash=source_hash,
            )

    if scheme_type == "apikey":
        location = str(scheme.get("in", "")).lower()
        name = str(scheme.get("name", ""))
        if location not in {"header", "query", "cookie"} or not name:
            warnings.append("OpenAPI apiKey scheme is incomplete; review its location and name.")
            return _plan(
                kind="unknown",
                confidence="low",
                warnings=warnings,
                source=source,
                source_hash=source_hash,
            )
        env_name = "LINGTEST_API_KEY"
        application = AuthApplication(
            header=name if location == "header" else None,
            query_name=name if location == "query" else None,
            cookie_name=name if location == "cookie" else None,
            template="{token}",
        )
        return _plan(
            kind="api_key",
            apply=application,
            token_env=env_name,
            required_env=[env_name],
            confidence="high",
            warnings=warnings,
            source=source,
            source_hash=source_hash,
        )

    if scheme_type == "oauth2":
        return _oauth2_plan(scheme, source, source_hash, warnings)

    warnings.append(f"OpenAPI auth scheme {scheme_type or 'unknown'!r} is not automated.")
    return _plan(
        kind="unknown",
        confidence="low",
        warnings=warnings,
        source=source,
        source_hash=source_hash,
    )


def _oauth2_plan(
    scheme: dict[str, Any], source: str, source_hash: str, warnings: list[str]
) -> AuthPlan:
    flows = scheme.get("flows")
    if not isinstance(flows, dict):
        return _plan(
            kind="unknown",
            confidence="low",
            warnings=[*warnings, "OAuth2 scheme has no flows object."],
            source=source,
            source_hash=source_hash,
        )

    flow_name = next((name for name in ("clientCredentials", "password") if name in flows), None)
    if flow_name is None:
        env_name = "LINGTEST_BEARER_TOKEN"
        return _plan(
            kind="bearer",
            apply=AuthApplication(header="Authorization", template="Bearer {token}"),
            token_env=env_name,
            required_env=[env_name],
            confidence="medium",
            warnings=[
                *warnings,
                "Interactive OAuth2 flows are not automated; provide a pre-issued test "
                "access token.",
            ],
            source=source,
            source_hash=source_hash,
        )

    flow = flows[flow_name]
    token_url = flow.get("tokenUrl")
    if not isinstance(token_url, str) or not token_url.strip():
        return _plan(
            kind="unknown",
            confidence="low",
            warnings=[*warnings, f"OAuth2 {flow_name} flow has no tokenUrl."],
            source=source,
            source_hash=source_hash,
        )

    body: dict[str, str]
    required_env: list[str]
    if flow_name == "password":
        username_env = "LINGTEST_USERNAME"
        password_env = "LINGTEST_PASSWORD"
        body = {
            "grant_type": "password",
            "username": f"${{{username_env}}}",
            "password": f"${{{password_env}}}",
        }
        required_env = [username_env, password_env]
        warnings.append(
            "Confirm the documented test role and token endpoint fields; OpenAPI may not "
            "describe the account policy."
        )
    else:
        client_id_env = "LINGTEST_CLIENT_ID"
        client_secret_env = "LINGTEST_CLIENT_SECRET"
        body = {
            "grant_type": "client_credentials",
            "client_id": f"${{{client_id_env}}}",
            "client_secret": f"${{{client_secret_env}}}",
        }
        required_env = [client_id_env, client_secret_env]

    try:
        login = LoginRequest(method="POST", path=token_url, content_type="form", body=body)
    except ValueError as exc:
        return _plan(
            kind="unknown",
            confidence="low",
            warnings=[*warnings, str(exc)],
            source=source,
            source_hash=source_hash,
        )
    return _plan(
        kind="bearer",
        login=login,
        extract=TokenExtraction(json_path="access_token"),
        apply=AuthApplication(header="Authorization", template="Bearer {token}"),
        required_env=required_env,
        confidence="medium" if flow_name == "password" else "high",
        warnings=warnings,
        source=source,
        source_hash=source_hash,
    )


def _selected_scheme(
    spec: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, bool]:
    schemes = spec.get("components", {}).get("securitySchemes", {})
    if not isinstance(schemes, dict) or not schemes:
        return None, None, False

    global_security = spec.get("security", [])
    effective: list[dict[str, Any]] = []
    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            if not isinstance(operation, dict):
                continue
            security = operation.get("security", global_security)
            if isinstance(security, list):
                effective.extend(item for item in security if isinstance(item, dict))
    if not effective and isinstance(global_security, list):
        effective.extend(item for item in global_security if isinstance(item, dict))
    requirements = [item for item in effective if item]
    if not requirements:
        return None, None, False

    required_names = {name for requirement in requirements for name in requirement}
    if len(required_names) > 1:
        return "multiple", None, True

    first = requirements[0]
    name = next(iter(first))
    scheme = schemes.get(name)
    if not isinstance(scheme, dict):
        return name, None, len(requirements) > 1
    ref = scheme.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/securitySchemes/"):
        ref_name = ref.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
        scheme = schemes.get(ref_name)
        name = ref_name
    if not isinstance(scheme, dict):
        return name, None, len(requirements) > 1
    return name, scheme, len(requirements) > 1


def _from_extension(extension: dict[str, Any], *, source: str, source_hash: str) -> AuthPlan:
    allowed = {
        "kind",
        "login",
        "extract",
        "apply",
        "token_env",
        "username_env",
        "password_env",
        "required_env",
        "confidence",
        "warnings",
    }
    unknown = set(extension) - allowed
    if unknown:
        raise ValueError(f"Unsupported x-lingtest-auth fields: {', '.join(sorted(unknown))}")
    draft = _sanitize_auth_extension(extension)
    return AuthPlan.model_validate(
        {
            **draft,
            "source": source,
            "source_sha256": source_hash,
        }
    )


def _sanitize_auth_extension(extension: dict[str, Any]) -> dict[str, Any]:
    """Keep accidental credential literals out of persisted OpenAPI auth plans."""
    from lingtest.auth.models import AuthPlanDraft
    from lingtest.auth.planner import _sanitize_draft

    draft = AuthPlanDraft.model_validate(extension)
    return _sanitize_draft(draft).model_dump(mode="json", exclude_none=True)


def _plan(
    *,
    kind: str,
    source: str,
    source_hash: str,
    confidence: str = "low",
    warnings: list[str] | None = None,
    login: LoginRequest | None = None,
    extract: TokenExtraction | None = None,
    apply: AuthApplication | None = None,
    token_env: str | None = None,
    username_env: str | None = None,
    password_env: str | None = None,
    required_env: list[str] | None = None,
) -> AuthPlan:
    return AuthPlan(
        kind=kind,
        login=login,
        extract=extract,
        apply=apply,
        token_env=token_env,
        username_env=username_env,
        password_env=password_env,
        required_env=required_env or [],
        confidence=confidence,
        warnings=warnings or [],
        source=source,
        source_sha256=source_hash,
    )


def _display_path(path: Path, root: str | Path | None) -> str:
    resolved = path.resolve()
    project = Path(root or Path.cwd()).resolve()
    if resolved == project or project in resolved.parents:
        return resolved.relative_to(project).as_posix()
    return resolved.name
