"""Bounded, opt-in local source retrieval for failure diagnosis."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".java",
    ".cs",
    ".rb",
    ".php",
    ".rs",
    ".kt",
    ".swift",
    ".sql",
}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".codex",
    ".lingtest",
}
SKIP_FILES = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials", "secrets"}
SECRET_LITERAL = re.compile(
    r"(?i)(['\"]?\b(?:password|passwd|client[_-]?secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|secret|private[_-]?key|database[_-]?url|db[_-]?url|"
    r"connection[_-]?string|dsn|username|user_name|email|user[_-]?id)\b['\"]?\s*[:=]\s*)"
    r"(['\"])([^'\"]{4,})\2"
)
BEARER_LITERAL = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{16,}={0,2}")
URL_CREDENTIALS = re.compile(
    r"(?i)(\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^:/@\s]+:)" r"[^@/\s]+(@)"
)
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
STOP_WORDS = {
    "http",
    "https",
    "status",
    "expected",
    "actual",
    "response",
    "request",
    "error",
    "failed",
    "failure",
    "test",
    "case",
    "true",
    "false",
    "none",
    "null",
    "string",
    "integer",
    "return",
    "async",
    "await",
    "public",
    "private",
    "class",
    "function",
}
MAX_SOURCE_FILES = 600
MAX_FILE_BYTES = 256_000
MAX_TOTAL_CHARS = 48_000
MAX_FILES_IN_CONTEXT = 12
MAX_SNIPPETS_PER_FILE = 5


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: str
    text: str
    line_count: int
    score: int


@dataclass(frozen=True, slots=True)
class SourceContext:
    root: Path
    files: tuple[SourceFile, ...]
    text: str

    @property
    def allowed_paths(self) -> dict[str, set[int]]:
        ranges: dict[str, set[int]] = {}
        for item in self.files:
            numbers = set()
            for line in item.text.splitlines():
                match = re.match(r"^(\d+):", line)
                if match:
                    numbers.add(int(match.group(1)))
            ranges[item.path] = numbers
        return ranges


def collect_source_context(
    report,
    root: str | Path,
    *,
    hints: list[str] | None = None,
) -> SourceContext:
    """Retrieve a bounded set of source/test snippets relevant to failed API cases.

    The caller must opt in by passing a source root. Git's file listing is used when available so
    ignored files remain excluded. The fallback walker skips common generated and local-state dirs.
    """

    project = Path(root).resolve()
    if not project.is_dir():
        raise ValueError(f"Source root is not a directory: {root}")
    files = _candidate_paths(project)
    clues = _failure_clues(report)
    hinted = _resolve_hints(project, hints or [])
    files = sorted(set(files).union(hinted), key=lambda item: item.as_posix().lower())
    scored: list[tuple[int, Path, str]] = []
    for path in files[:MAX_SOURCE_FILES]:
        try:
            resolved = path.resolve()
            if resolved != project and project not in resolved.parents:
                continue
            if path.is_symlink():
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        safe = _redact_source(raw)
        relative = path.relative_to(project).as_posix()
        score = _score(relative, safe, clues)
        if path in hinted:
            score += 100
        if score:
            scored.append((score, path, safe))
    scored.sort(key=lambda item: (-item[0], item[1].as_posix().lower()))

    selected: list[SourceFile] = []
    total = 0
    for score, path, source in scored[:MAX_FILES_IN_CONTEXT]:
        relative = path.relative_to(project).as_posix()
        excerpt = _excerpt(source, clues)
        excerpt = excerpt[: max(0, MAX_TOTAL_CHARS - total)]
        if not excerpt.strip():
            break
        selected.append(
            SourceFile(
                path=relative,
                text=excerpt,
                line_count=len(source.splitlines()),
                score=score,
            )
        )
        total += len(excerpt)
        if total >= MAX_TOTAL_CHARS:
            break

    rendered = "\n\n".join(
        f"### {item.path} (relevance={item.score}; total_lines={item.line_count})\n{item.text}"
        for item in selected
    )
    if not rendered:
        rendered = "No relevant source snippets were found within the configured local source root."
    return SourceContext(root=project, files=tuple(selected), text=rendered)


def _candidate_paths(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=4,
            check=True,
        )
        listed = [root / item for item in result.stdout.splitlines()]
    except (OSError, subprocess.SubprocessError):
        listed = []
        for parent, dirs, names in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
            listed.extend(Path(parent) / name for name in names)

    selected = []
    for path in listed:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        if path.name.lower() in SKIP_FILES or path.name.lower().startswith(".env"):
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES or not path.is_file():
            continue
        selected.append(path)
    return sorted(set(selected), key=lambda item: item.as_posix().lower())


def _failure_clues(report) -> set[str]:
    parts: list[str] = []
    for result in report.results:
        if result.status in {"passed", "skipped", "blocked"}:
            continue
        parts.extend([result.case_id, result.title, result.path, result.error or ""])
        parts.extend(result.logs)
    words = {word.lower() for part in parts for word in WORD.findall(part)}
    return {word for word in words if word not in STOP_WORDS and not word.isdigit()}


def _resolve_hints(root: Path, hints: list[str]) -> set[Path]:
    resolved: set[Path] = set()
    for hint in hints:
        path = Path(hint)
        candidate = (root / path).resolve() if not path.is_absolute() else path.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError(f"Source hint escapes the source root: {hint}")
        if candidate.is_file() and candidate.suffix.lower() in SOURCE_SUFFIXES:
            resolved.add(candidate)
    return resolved


def _score(relative: str, content: str, clues: set[str]) -> int:
    lowered_path = relative.lower()
    lowered_content = content.lower()
    score = sum(5 for clue in clues if clue in lowered_path)
    for clue in clues:
        count = lowered_content.count(clue)
        if count:
            score += min(count, 5)
    if "test" in lowered_path or "spec" in lowered_path:
        score += 1
    return score


def _excerpt(source: str, clues: set[str]) -> str:
    lines = source.splitlines()
    matches = [
        index for index, line in enumerate(lines) if any(clue in line.lower() for clue in clues)
    ]
    if not matches:
        matches = list(range(min(12, len(lines))))
    windows: list[tuple[int, int]] = []
    for index in matches:
        start, end = max(0, index - 2), min(len(lines), index + 3)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
        if len(windows) >= MAX_SNIPPETS_PER_FILE:
            break
    return "\n".join(
        f"{line_index + 1}: {lines[line_index]}"
        for start, end in windows
        for line_index in range(start, end)
    )


def _redact_source(source: str) -> str:
    lines: list[str] = []
    for line in source.splitlines():
        cleaned = SECRET_LITERAL.sub(r"\1[REDACTED]", line)
        cleaned = BEARER_LITERAL.sub(r"\1[REDACTED]", cleaned)
        cleaned = URL_CREDENTIALS.sub(r"\1[REDACTED]\2", cleaned)
        lines.append(cleaned)
    return "\n".join(lines)
