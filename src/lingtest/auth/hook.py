"""Validation for explicitly trusted Python authentication hooks."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from lingtest.auth.models import AuthHook


def validate_auth_hook(reference: str, *, project_root: str | Path | None = None) -> AuthHook:
    """Validate ``path.py:function`` without importing or executing the module."""

    path_text, separator, function = reference.rpartition(":")
    if not separator or not path_text or not function.isidentifier():
        raise ValueError("Auth hook must use PATH.py:FUNCTION syntax")
    root = Path(project_root or Path.cwd()).resolve()
    path = Path(path_text)
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("Auth hook must be located inside the project")
    if resolved.suffix.lower() != ".py" or not resolved.is_file():
        raise ValueError("Auth hook must reference an existing Python file")

    source = resolved.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(resolved))
    except SyntaxError as exc:
        raise ValueError(f"Invalid auth hook Python: {exc}") from exc
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
    ]
    if len(matches) != 1:
        raise ValueError(f"Auth hook must define one top-level function named {function!r}")
    if isinstance(matches[0], ast.AsyncFunctionDef):
        raise ValueError("Async auth hooks are not supported in the first version")
    if not matches[0].args.args:
        raise ValueError("Auth hook function must accept an httpx.Request argument")

    display_path = str(resolved.relative_to(root)).replace("\\", "/")
    return AuthHook(
        path=display_path,
        function=function,
        sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )
