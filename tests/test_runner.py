import httpx

from lingtest.models import TestCase as ApiTestCase
from lingtest.runner import run_cases


def test_run_cases(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

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

    report = run_cases([case], "https://example.test")

    assert report.passed == 1
    assert report.failed == 0
