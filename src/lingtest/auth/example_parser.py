"""Static AST extraction of common token and cookie authentication examples."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from lingtest.auth.models import AuthApplication, AuthPlan, LoginRequest, TokenExtraction

MAX_AUTH_EXAMPLE_CHARS = 100_000
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "request"}
LOGIN_HINTS = ("login", "token", "auth", "session", "signin", "sign-in")
SECRET_FIELDS = ("password", "passwd", "secret", "token", "api_key", "apikey")


def analyze_auth_example(path: str | Path, *, project_root: str | Path | None = None) -> AuthPlan:
    """Extract an AuthPlan without importing or executing the supplied Python."""

    source_path = Path(path)
    if source_path.suffix.lower() != ".py" or not source_path.is_file():
        raise ValueError("Authentication example must be an existing .py file")
    source = source_path.read_text(encoding="utf-8")
    if len(source) > MAX_AUTH_EXAMPLE_CHARS:
        raise ValueError("Authentication example is too large")
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        raise ValueError(f"Invalid authentication example: {exc}") from exc

    calls = _request_calls(tree)
    login_var, login_call = _choose_login_call(calls)
    token_var, token_path = _find_token_extraction(tree, login_var)
    application = _find_application(tree, token_var)
    warnings: list[str] = []
    required_env: set[str] = set()

    login = None
    if login_call is not None:
        path_value = _call_path(login_call)
        body, content_type = _call_body(login_call, required_env, warnings)
        if path_value:
            login = LoginRequest(
                method=_call_method(login_call),
                path=path_value,
                content_type=content_type,
                body=body,
            )

    if application and application.header:
        kind = "bearer"
    elif login is not None and _uses_client_session(tree):
        kind = "cookie"
        application = application or AuthApplication(cookie_name=None)
    else:
        kind = "unknown"

    extraction = None
    if token_path:
        extraction = TokenExtraction(json_path=token_path)
    elif kind == "cookie":
        extraction = TokenExtraction(cookie_name=None)

    confidence = "low"
    if login and kind == "cookie":
        confidence = "medium"
    if login and extraction and application and kind == "bearer":
        confidence = "high"
    elif login and application:
        confidence = "medium"
    if kind == "unknown":
        warnings.append("Could not determine how authentication is applied; review manually")

    root = Path(project_root or Path.cwd()).resolve()
    resolved = source_path.resolve()
    display = (
        str(resolved.relative_to(root)).replace("\\", "/")
        if root == resolved or root in resolved.parents
        else str(resolved)
    )
    return AuthPlan(
        kind=kind,
        login=login,
        extract=extraction,
        apply=application,
        required_env=sorted(required_env),
        confidence=confidence,
        source=display,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        warnings=warnings,
    )


def _request_calls(tree: ast.AST) -> list[tuple[str | None, ast.Call]]:
    results: list[tuple[str | None, ast.Call]] = []
    for node in ast.walk(tree):
        value = None
        target = None
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = _name(node.targets[0])
            elif isinstance(node, ast.AnnAssign):
                target = _name(node.target)
        elif isinstance(node, ast.Expr):
            value = node.value
        if isinstance(value, ast.Call) and _call_method_name(value) in HTTP_METHODS:
            results.append((target, value))
    return results


def _choose_login_call(
    calls: list[tuple[str | None, ast.Call]],
) -> tuple[str | None, ast.Call | None]:
    for variable, call in calls:
        path = (_call_path(call) or "").lower()
        if any(hint in path for hint in LOGIN_HINTS):
            return variable, call
    return calls[0] if calls else (None, None)


def _find_token_extraction(
    tree: ast.AST, response_var: str | None
) -> tuple[str | None, str | None]:
    if not response_var:
        return None, None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = _name(node.targets[0])
        path = _json_subscript_path(node.value, response_var)
        if target and path:
            return target, ".".join(path)
    return None, None


def _json_subscript_path(node: ast.AST, response_var: str) -> list[str] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Subscript):
        key = _literal_string(current.slice)
        if key is None:
            return None
        parts.insert(0, key)
        current = current.value
    if not isinstance(current, ast.Call) or not isinstance(current.func, ast.Attribute):
        return None
    if current.func.attr != "json" or _name(current.func.value) != response_var:
        return None
    return parts


def _find_application(tree: ast.AST, token_var: str | None) -> AuthApplication | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Subscript):
            continue
        key = _literal_string(target.slice)
        if key and key.lower() == "authorization":
            template = _string_template(node.value, token_var)
            return AuthApplication(header=key, template=template or "Bearer {token}")
    return None


def _call_method(call: ast.Call) -> str:
    name = _call_method_name(call)
    if name == "request" and call.args:
        literal = _literal_string(call.args[0])
        if literal:
            return literal.upper()
    return (name or "POST").upper()


def _call_path(call: ast.Call) -> str | None:
    index = 1 if _call_method_name(call) == "request" else 0
    if len(call.args) > index:
        return _literal_string(call.args[index])
    for keyword in call.keywords:
        if keyword.arg in {"url", "path"}:
            return _literal_string(keyword.value)
    return None


def _call_body(
    call: ast.Call,
    required_env: set[str],
    warnings: list[str],
) -> tuple[dict[str, str], str]:
    body: dict[str, str] = {}
    content_type = "json"
    for keyword in call.keywords:
        if keyword.arg not in {"json", "data"} or not isinstance(keyword.value, ast.Dict):
            continue
        content_type = "form" if keyword.arg == "data" else "json"
        for key_node, value_node in zip(keyword.value.keys, keyword.value.values, strict=True):
            key = _literal_string(key_node) if key_node else None
            if not key:
                continue
            env_name = _environment_name(value_node)
            if env_name:
                required_env.add(env_name)
                body[key] = f"${{{env_name}}}"
                continue
            value = _literal_string(value_node)
            if value is not None:
                if any(marker in key.lower() for marker in SECRET_FIELDS):
                    inferred = _infer_env_name(key)
                    required_env.add(inferred)
                    body[key] = f"${{{inferred}}}"
                    warnings.append(f"Replaced a literal value for {key!r} with {inferred}")
                else:
                    body[key] = value
    return body, content_type


def _environment_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
        if _name(node.value.value) == "os" and node.value.attr == "environ":
            return _literal_string(node.slice)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if _name(node.func.value) == "os" and node.func.attr == "getenv" and node.args:
            return _literal_string(node.args[0])
    return None


def _string_template(node: ast.AST, token_var: str | None) -> str | None:
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and _name(value.value) == token_var:
                parts.append("{token}")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left)
        if left is not None and _name(node.right) == token_var:
            return left + "{token}"
    return _literal_string(node)


def _uses_client_session(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name(node.func)
            if name in {"httpx.Client", "requests.Session"}:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"Client", "Session"}:
                return True
    return False


def _call_method_name(call: ast.Call) -> str | None:
    return call.func.attr.lower() if isinstance(call.func, ast.Attribute) else None


def _literal_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _infer_env_name(field: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", field).strip("_").upper()
    return f"TEST_{normalized or 'SECRET'}"
