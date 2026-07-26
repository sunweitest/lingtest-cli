"""HTTP runner that captures redacted request, response, timing, and diagnostic logs."""

from time import perf_counter

import httpx

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
) -> RunReport:
    results: list[TestResult] = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        for case in cases:
            started = perf_counter()
            actual_status = None
            error = None
            response_headers: dict[str, str] = {}
            response_body = None
            status = "error"
            merged_headers = {**case.headers, **(extra_headers or {})}
            logs = [f"Preparing {case.method.upper()} {case.path}"]
            try:
                response = client.request(
                    case.method,
                    case.path,
                    params=case.query,
                    headers=merged_headers,
                    json=case.body,
                )
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
            except httpx.HTTPError as exc:
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


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        name: "[REDACTED]" if name.lower() in SENSITIVE_HEADERS else value
        for name, value in headers.items()
    }
