"""HTTP runner that captures redacted request, response, timing, and diagnostic logs."""

from pathlib import Path
from time import perf_counter

import httpx

from lingtest.auth.models import AuthHook, AuthPlan
from lingtest.auth.runtime import build_authenticated_client, load_auth_hook
from lingtest.models import RunReport, TestCase, TestResult

SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
}
MAX_RESPONSE_CHARS = 20_000


def run_cases(
    cases: list[TestCase],
    base_url: str,
    *,
    timeout: float = 10.0,
    extra_headers: dict[str, str] | None = None,
    auth_plan: AuthPlan | None = None,
    auth_hook: AuthHook | None = None,
    project_root: str | Path | None = None,
) -> RunReport:
    results: list[TestResult] = []
    try:
        client = build_authenticated_client(base_url, timeout=timeout, plan=auth_plan)
        selected_hook = auth_hook or (auth_plan.hook if auth_plan else None)
        hook_callback = (
            load_auth_hook(selected_hook, project_root=project_root) if selected_hook else None
        )
    except Exception as exc:
        return _setup_error_report(cases, base_url, exc)

    with client:
        for case in cases:
            started = perf_counter()
            actual_status = None
            error = None
            response_headers: dict[str, str] = {}
            response_body = None
            status = "error"
            merged_headers = {**case.headers, **(extra_headers or {})}
            logs = [f"Preparing {case.method.upper()} {case.path}"]
            if auth_plan:
                logs.append(f"Using reviewed authentication plan: {auth_plan.kind}")
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
                response_body = response.text[:MAX_RESPONSE_CHARS]
                status = "passed" if actual_status == case.expected_status else "failed"
                logs.append(f"Received HTTP {actual_status}")
                if status == "failed":
                    error = f"expected HTTP {case.expected_status}, got HTTP {actual_status}"
                    logs.append(error)
                else:
                    logs.append(f"Matched expected HTTP {case.expected_status}")
            except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                error = str(exc)
                logs.append(f"Request error: {exc}")
            results.append(
                TestResult(
                    case_id=case.id,
                    title=case.title,
                    status=status,
                    duration_ms=(perf_counter() - started) * 1000,
                    expected_status=case.expected_status,
                    actual_status=actual_status,
                    error=error,
                    method=case.method.upper(),
                    path=case.path,
                    request_headers=_redact_headers(merged_headers),
                    query=case.query,
                    request_body=case.body,
                    response_headers=response_headers,
                    response_body=response_body,
                    logs=logs,
                )
            )
    return RunReport(base_url=base_url, results=results)


def _setup_error_report(cases: list[TestCase], base_url: str, exc: Exception) -> RunReport:
    message = f"Authentication setup failed: {exc}"
    return RunReport(
        base_url=base_url,
        results=[
            TestResult(
                case_id=case.id,
                title=case.title,
                status="error",
                duration_ms=0,
                expected_status=case.expected_status,
                error=message,
                method=case.method.upper(),
                path=case.path,
                logs=[message],
            )
            for case in cases
        ],
    )


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: "[REDACTED]" if name.lower() in SENSITIVE_HEADERS else value
        for name, value in headers.items()
    }
