"""HTTP runner that captures redacted request, response, timing, and diagnostic logs."""

import re
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

import httpx

from lingtest.auth.models import AuthHook, AuthPlan
from lingtest.auth.runtime import build_authenticated_client, load_auth_hook
from lingtest.models import InputRequest, RunReport, TestCase, TestResult

SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
}
MAX_RESPONSE_CHARS = 20_000
BEARER_LITERAL = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{16,}={0,2}")
URL_CREDENTIALS = re.compile(
    r"(?i)(\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://[^:/@\s]+:)" r"[^@/\s]+(@)"
)


def run_cases(
    cases: list[TestCase],
    base_url: str,
    *,
    timeout: float = 10.0,
    extra_headers: dict[str, str] | None = None,
    auth_plan: AuthPlan | None = None,
    auth_hook: AuthHook | None = None,
    project_root: str | Path | None = None,
    event_callback: Callable[[str, dict], None] | None = None,
    input_requests: list[InputRequest] | None = None,
    approval_records: list[dict] | None = None,
    input_resolutions: list[dict] | None = None,
) -> RunReport:
    started_at = datetime.now(UTC)
    results: list[TestResult] = []
    selected_hook = auth_hook or (auth_plan.hook if auth_plan else None)
    required_inputs = [item for item in input_requests or [] if item.required]
    if required_inputs:
        details = "; ".join(f"{item.request_id}: {item.prompt}" for item in required_inputs)
        return _blocked_report(
            cases,
            base_url,
            "Required test-planning input is unresolved: " + details,
            project_root=project_root,
            event_callback=event_callback,
            error_category="missing_input",
            approval_records=approval_records,
            input_resolutions=input_resolutions,
        )
    if any(
        case.requires_auth and case.expected_status != 401 for case in cases
    ) and not _has_usable_auth(auth_plan, selected_hook):
        return _blocked_report(
            cases,
            base_url,
            "OpenAPI marks one or more operations as authenticated, but no usable auth plan or "
            "approved auth hook was provided. Create/review one with `lingtest auth-plan`, then "
            "rerun with `--auth-plan`.",
            project_root=project_root,
            event_callback=event_callback,
            approval_records=approval_records,
            input_resolutions=input_resolutions,
        )
    try:
        client = build_authenticated_client(base_url, timeout=timeout, plan=auth_plan)
        hook_callback = (
            load_auth_hook(selected_hook, project_root=project_root) if selected_hook else None
        )
    except Exception as exc:
        return _setup_error_report(
            cases,
            base_url,
            exc,
            project_root=project_root,
            event_callback=event_callback,
            approval_records=approval_records,
            input_resolutions=input_resolutions,
        )

    with closing(client):
        for case in cases:
            _emit_run_event(
                event_callback,
                "test_started",
                {"case_id": case.id, "method": case.method.upper(), "path": case.path},
            )
            if (case.data_prerequisites or case.data_setup) and not case.data_ready:
                blocked_at = datetime.now(UTC)
                message = (
                    "Required test data is not confirmed as ready. Prepare it with an existing "
                    "project fixture or documented test API, then review the case and set "
                    "data_ready=true before rerunning. LingTest does not create data through "
                    "arbitrary database credentials or SQL."
                )
                result = TestResult(
                    case_id=case.id,
                    title=case.title,
                    status="blocked",
                    duration_ms=0,
                    started_at=blocked_at,
                    finished_at=blocked_at,
                    expected_status=case.expected_status,
                    expected_result=case.expected_result,
                    steps=case.steps,
                    user_role=case.user_role,
                    data_prerequisites=case.data_prerequisites,
                    data_setup=case.data_setup,
                    data_cleanup=case.data_cleanup,
                    data_ready=case.data_ready,
                    requirement_refs=case.requirement_refs,
                    requires_auth=case.requires_auth,
                    evidence_refs=[f"{case.id}.test_data"],
                    error_category="test_data",
                    error=message,
                    method=case.method.upper(),
                    path=case.path,
                    logs=[message],
                )
                results.append(result)
                _emit_test_result(event_callback, result)
                continue
            if _is_auth_setup_case(case, auth_plan):
                skipped_at = datetime.now(UTC)
                result = TestResult(
                    case_id=case.id,
                    title=case.title,
                    status="skipped",
                    duration_ms=0,
                    started_at=skipped_at,
                    finished_at=skipped_at,
                    expected_status=case.expected_status,
                    expected_result=case.expected_result,
                    steps=case.steps,
                    user_role=case.user_role,
                    data_prerequisites=case.data_prerequisites,
                    data_setup=case.data_setup,
                    data_cleanup=case.data_cleanup,
                    data_ready=case.data_ready,
                    requirement_refs=case.requirement_refs,
                    requires_auth=case.requires_auth,
                    evidence_refs=[f"{case.id}.logs"],
                    method=case.method.upper(),
                    path=case.path,
                    error=(
                        "This login operation was exercised by auth setup; "
                        "duplicate request skipped."
                    ),
                    logs=["Authentication setup already exercised this token endpoint."],
                )
                results.append(result)
                _emit_test_result(event_callback, result)
                continue
            started = perf_counter()
            case_started_at = datetime.now(UTC)
            actual_status = None
            error = None
            response_headers: dict[str, str] = {}
            response_body = None
            status = "error"
            error_category = None
            merged_headers = {**case.headers, **(extra_headers or {})}
            logs = [f"Preparing {case.method.upper()} {case.path}"]
            if auth_plan:
                logs.append(f"Using reviewed authentication plan: {auth_plan.kind}")
            if hook_callback is not None:
                logs.append("Authentication hook setup succeeded")
            elif auth_plan and auth_plan.kind not in {"none", "unknown"}:
                logs.append("Authentication plan setup succeeded")
            try:
                request = client.build_request(
                    case.method,
                    case.path,
                    params=case.query,
                    headers=merged_headers,
                    json=case.body,
                )
                if hook_callback is not None:
                    hook_callback(request)
                    logs.append("Applied approved authentication hook")
                response = client.send(request)
                actual_status = response.status_code
                response_headers = _redact_headers(dict(response.headers))
                response_body = _redact_response_body(response)
                status = "passed" if actual_status == case.expected_status else "failed"
                if (
                    status == "failed"
                    and actual_status in {401, 403}
                    and not _has_usable_auth(auth_plan, selected_hook)
                ):
                    status = "blocked"
                    error = (
                        f"received HTTP {actual_status} without usable auth setup; "
                        "confirm the login flow and rerun before treating this as an API failure"
                    )
                logs.append(f"Received HTTP {actual_status}")
                if status == "failed":
                    error = f"expected HTTP {case.expected_status}, got HTTP {actual_status}"
                    error_category = "authorization" if actual_status in {401, 403} else "assertion"
                    logs.append(error)
                elif status == "blocked":
                    error_category = "authentication_setup"
                    logs.append(
                        "Authentication prerequisite is unresolved; "
                        "this is not counted as a product failure"
                    )
                else:
                    logs.append(f"Matched expected HTTP {case.expected_status}")
            except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                error = _redact_text(str(exc))
                error_category = (
                    "environment" if isinstance(exc, httpx.HTTPError | OSError) else "unknown"
                )
                logs.append(f"Request error: {error}")
            finished_at = datetime.now(UTC)
            result = TestResult(
                case_id=case.id,
                title=case.title,
                status=status,
                duration_ms=(perf_counter() - started) * 1000,
                started_at=case_started_at,
                finished_at=finished_at,
                expected_status=case.expected_status,
                expected_result=case.expected_result,
                steps=case.steps,
                user_role=case.user_role,
                data_prerequisites=case.data_prerequisites,
                data_setup=case.data_setup,
                data_cleanup=case.data_cleanup,
                data_ready=case.data_ready,
                actual_status=actual_status,
                requirement_refs=case.requirement_refs,
                requires_auth=case.requires_auth,
                evidence_refs=[
                    f"{case.id}.actual_status" if actual_status is not None else f"{case.id}.error"
                ],
                error_category=error_category,
                error=error,
                method=case.method.upper(),
                path=case.path,
                request_headers=_redact_headers(merged_headers),
                query=_redact_payload(case.query),
                request_body=_redact_payload(case.body),
                response_headers=response_headers,
                response_body=response_body,
                logs=logs,
            )
            results.append(result)
            _emit_test_result(event_callback, result)
    return RunReport(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        base_url=_report_base_url(base_url),
        revision=_git_revision(project_root),
        working_tree_dirty=_git_working_tree_dirty(project_root),
        results=results,
        approvals=approval_records or [],
        input_resolutions=input_resolutions or [],
    )


def _setup_error_report(
    cases: list[TestCase],
    base_url: str,
    exc: Exception,
    *,
    project_root: str | Path | None = None,
    event_callback: Callable[[str, dict], None] | None = None,
    approval_records: list[dict] | None = None,
    input_resolutions: list[dict] | None = None,
) -> RunReport:
    message = _redact_text(f"Authentication preflight blocked execution: {exc}")
    return _blocked_report(
        cases,
        base_url,
        message,
        project_root=project_root,
        event_callback=event_callback,
        approval_records=approval_records,
        input_resolutions=input_resolutions,
    )


def _blocked_report(
    cases: list[TestCase],
    base_url: str,
    message: str,
    *,
    project_root: str | Path | None = None,
    event_callback: Callable[[str, dict], None] | None = None,
    error_category: str = "authentication_setup",
    approval_records: list[dict] | None = None,
    input_resolutions: list[dict] | None = None,
) -> RunReport:
    blocked_at = datetime.now(UTC)
    results = [
        TestResult(
            case_id=case.id,
            title=case.title,
            status="blocked",
            duration_ms=0,
            started_at=blocked_at,
            finished_at=blocked_at,
            expected_status=case.expected_status,
            expected_result=case.expected_result,
            steps=case.steps,
            user_role=case.user_role,
            data_prerequisites=case.data_prerequisites,
            data_setup=case.data_setup,
            data_cleanup=case.data_cleanup,
            data_ready=case.data_ready,
            requirement_refs=case.requirement_refs,
            requires_auth=case.requires_auth,
            evidence_refs=[f"{case.id}.error"],
            error_category=error_category,
            error=message,
            method=case.method.upper(),
            path=case.path,
            logs=[message],
        )
        for case in cases
    ]
    for result in results:
        _emit_run_event(
            event_callback,
            "test_started",
            {"case_id": result.case_id, "method": result.method, "path": result.path},
        )
        _emit_test_result(event_callback, result)
    return RunReport(
        started_at=blocked_at,
        finished_at=blocked_at,
        base_url=_report_base_url(base_url),
        revision=_git_revision(project_root),
        working_tree_dirty=_git_working_tree_dirty(project_root),
        results=results,
        approvals=approval_records or [],
        input_resolutions=input_resolutions or [],
    )


def _emit_test_result(callback: Callable[[str, dict], None] | None, result: TestResult) -> None:
    _emit_run_event(
        callback,
        "test_result",
        {
            "case_id": result.case_id,
            "status": result.status,
            "error_category": result.error_category,
            "actual_status": result.actual_status,
            "evidence_refs": result.evidence_refs,
        },
    )


def _emit_run_event(
    callback: Callable[[str, dict], None] | None,
    event_type: str,
    data: dict,
) -> None:
    if callback is None:
        return
    try:
        callback(event_type, data)
    except Exception:
        # Event transport must not change the API result being observed.
        return


def _has_usable_auth(plan: AuthPlan | None, hook: AuthHook | None) -> bool:
    if hook is not None:
        return True
    if plan is None or plan.kind in {"none", "unknown"}:
        return False
    if plan.kind == "custom_hook":
        return plan.hook is not None
    return True


def _report_base_url(value: str) -> str:
    """Keep userinfo, query credentials, and fragments out of durable reports."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if host is None:
            return "<invalid-url>"
        safe_host = f"[{host}]" if ":" in host else host
        safe_netloc = safe_host + (f":{parsed.port}" if parsed.port is not None else "")
        return urlunsplit((parsed.scheme, safe_netloc, parsed.path, "", ""))
    except ValueError:
        return "<invalid-url>"


def _is_auth_setup_case(case: TestCase, plan: AuthPlan | None) -> bool:
    if plan is None or plan.login is None:
        return False
    expected_path = plan.login.path.split("?", 1)[0].strip("/")
    case_paths = {case.path, case.path_template or case.path}
    return case.method.upper() == plan.login.method.upper() and any(
        path.split("?", 1)[0].strip("/") == expected_path for path in case_paths
    )


def _redact_payload(value):
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _sensitive_name(str(key)) else _redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _sensitive_name(value: str) -> bool:
    normalized = value.lower().replace("-", "_")
    if normalized in {"authorization", "proxy_authorization", "cookie", "set_cookie"}:
        return True
    return any(
        marker in normalized
        for marker in ("password", "passwd", "secret", "token", "api_key", "credential")
    )


def _redact_text(value: str) -> str:
    pattern = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|credential)(\s*[:=]\s*)([^\s,;}]+)"
    )
    cleaned = pattern.sub(r"\1\2[REDACTED]", value)
    cleaned = BEARER_LITERAL.sub(r"\1[REDACTED]", cleaned)
    return URL_CREDENTIALS.sub(r"\1[REDACTED]\2", cleaned)


def _redact_response_body(response: httpx.Response) -> str:
    text = response.text[:MAX_RESPONSE_CHARS]
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        return _redact_text(text)
    import json

    return json.dumps(_redact_payload(payload), ensure_ascii=False)[:MAX_RESPONSE_CHARS]


def _git_revision(project_root: str | Path | None) -> str | None:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=project_root or Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def _git_working_tree_dirty(project_root: str | Path | None) -> bool | None:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root or Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(result.stdout.strip())


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: "[REDACTED]" if name.lower() in SENSITIVE_HEADERS or _sensitive_name(name) else value
        for name, value in headers.items()
    }
