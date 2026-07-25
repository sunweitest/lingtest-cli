from time import perf_counter

import httpx

from lingtest.models import RunReport, TestCase, TestResult


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
            status = "error"
            try:
                response = client.request(
                    case.method,
                    case.path,
                    params=case.query,
                    headers={**case.headers, **(extra_headers or {})},
                    json=case.body,
                )
                actual_status = response.status_code
                status = "passed" if actual_status == case.expected_status else "failed"
                if status == "failed":
                    error = f"expected HTTP {case.expected_status}, got HTTP {actual_status}"
            except httpx.HTTPError as exc:
                error = str(exc)
            results.append(
                TestResult(
                    case_id=case.id,
                    title=case.title,
                    status=status,
                    duration_ms=(perf_counter() - started) * 1000,
                    expected_status=case.expected_status,
                    actual_status=actual_status,
                    error=error,
                )
            )
    return RunReport(base_url=base_url, results=results)

