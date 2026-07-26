import httpx

from lingtest.artifacts import read_cases, write_cases, write_test_script
from lingtest.html_report import render_html_report
from lingtest.models import TestCase as ApiTestCase
from lingtest.observable_runner import run_cases


def test_yaml_dataset_and_python_script(tmp_path) -> None:
    cases = [
        ApiTestCase(
            id="health",
            title="Health",
            method="GET",
            path="/health",
            expected_status=200,
        )
    ]
    yaml_path = tmp_path / "cases.yaml"
    script_path = tmp_path / "test_api.py"

    write_cases(cases, yaml_path)
    loaded = read_cases(yaml_path)
    write_test_script(loaded, script_path)

    assert loaded == cases
    source = script_path.read_text(encoding="utf-8")
    assert "@pytest.mark.parametrize" in source
    assert '"path": "/health"' in source


def test_observable_html_report_redacts_secrets(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"ok": True}, headers={"x-trace-id": "trace-1"})

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    case = ApiTestCase(
        id="health",
        title="Health",
        method="GET",
        path="/health",
        expected_status=200,
    )

    report = run_cases(
        [case],
        "https://example.test",
        extra_headers={"Authorization": "Bearer secret"},
    )
    rendered = render_html_report(report)

    assert report.passed == 1
    assert report.results[0].request_headers["Authorization"] == "[REDACTED]"
    assert "Bearer secret" not in rendered
    assert "Received HTTP 200" in rendered
    assert "trace-1" in rendered
    assert "filterCases" in rendered
