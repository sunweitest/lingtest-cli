from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import yaml
from pydantic import ValidationError

from lingtest.auth.openapi import analyze_openapi_auth
from lingtest.html_report import render_html_report
from lingtest.models import (
    InputRequest,
    RootCauseCandidate,
    RunReport,
)
from lingtest.models import (
    TestCase as ApiTestCase,
)
from lingtest.models import (
    TestResult as ApiTestResult,
)
from lingtest.observable_runner import run_cases
from lingtest.orchestration.engine import WorkflowEngine
from lingtest.orchestration.inputs import sanitize_answers
from lingtest.orchestration.state import WorkflowState


def test_oauth_password_plan_logs_in_before_protected_case(tmp_path, monkeypatch) -> None:
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(
        json.dumps(
            {
                "openapi": "3.0.3",
                "paths": {
                    "/token": {"post": {"responses": {"200": {"description": "token"}}}},
                    "/private": {
                        "get": {
                            "security": [{"oauth": ["read"]}],
                            "responses": {"200": {"description": "ok"}},
                        }
                    },
                },
                "components": {
                    "securitySchemes": {
                        "oauth": {
                            "type": "oauth2",
                            "flows": {
                                "password": {
                                    "tokenUrl": "/token",
                                    "scopes": {"read": "Read access"},
                                }
                            },
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    plan = analyze_openapi_auth(spec_path, project_root=tmp_path)
    assert plan is not None and plan.login is not None
    assert plan.login.body == {
        "grant_type": "password",
        "username": "${LINGTEST_USERNAME}",
        "password": "${LINGTEST_PASSWORD}",
    }

    monkeypatch.setenv("LINGTEST_USERNAME", "test-user")
    monkeypatch.setenv("LINGTEST_PASSWORD", "local-only-password")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/token":
            form = parse_qs(request.read().decode("utf-8"))
            assert form["username"] == ["test-user"]
            assert form["password"] == ["local-only-password"]
            return httpx.Response(200, json={"access_token": "short-lived-token"})
        assert request.headers["authorization"] == "Bearer short-lived-token"
        return httpx.Response(200, json={"ok": True})

    original_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    report = run_cases(
        [
            ApiTestCase(
                id="private-read",
                title="Private read",
                method="GET",
                path="/private",
                expected_status=200,
                requires_auth=True,
            )
        ],
        "https://api.example.test",
        auth_plan=plan,
    )

    assert requests == ["/token", "/private"], report.results[0].error
    assert report.passed == 1
    assert "local-only-password" not in report.model_dump_json()
    assert "short-lived-token" not in report.model_dump_json()


def test_openapi_auth_extension_removes_inline_credentials(tmp_path) -> None:
    spec_path = tmp_path / "openapi.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "openapi": "3.0.3",
                "paths": {},
                "x-lingtest-auth": {
                    "kind": "bearer",
                    "login": {
                        "method": "POST",
                        "path": "/token",
                        "body": {"username": "inline-user", "password": "inline-secret"},
                    },
                    "extract": {"json_path": "access_token"},
                    "apply": {"header": "Authorization", "template": "Bearer {token}"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = analyze_openapi_auth(spec_path, project_root=tmp_path)

    assert plan is not None and plan.login is not None
    assert plan.login.body["username"] == "${LINGTEST_USERNAME}"
    assert plan.login.body["password"] == "${LINGTEST_PASSWORD}"
    assert "inline-secret" not in plan.model_dump_json()
    assert "inline-user" not in plan.model_dump_json()


def test_secret_answers_store_only_environment_variable_name(monkeypatch) -> None:
    request = InputRequest(
        request_id="login-password",
        field="password",
        prompt="Enter password",
    )
    monkeypatch.setenv("LINGTEST_TEST_PASSWORD", "local-secret-value")

    answer = sanitize_answers([request], {"login-password": {"env_var": "LINGTEST_TEST_PASSWORD"}})

    assert answer == {"login-password": {"env_var": "LINGTEST_TEST_PASSWORD"}}
    assert "local-secret-value" not in json.dumps(answer)
    with pytest.raises(ValueError, match="env_var"):
        sanitize_answers([request], {"login-password": "local-secret-value"})


def test_absolute_or_query_bearing_case_paths_are_rejected() -> None:
    for path in (
        "https://other.example.test/steal",
        "//other.example.test/steal",
        "/private?token=secret",
        "/private#fragment",
    ):
        with pytest.raises(ValidationError):
            ApiTestCase(
                id="unsafe",
                title="Unsafe route",
                method="GET",
                path=path,
                expected_status=200,
            )


def test_missing_auth_blocks_protected_requests(monkeypatch) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    original_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    report = run_cases(
        [
            ApiTestCase(
                id="protected",
                title="Protected endpoint",
                method="GET",
                path="/private",
                expected_status=200,
                requires_auth=True,
            )
        ],
        "https://api.example.test",
    )

    assert report.blocked == 1
    assert report.results[0].error_category == "authentication_setup"
    assert not called


def test_report_renders_evidence_linked_root_cause_candidate() -> None:
    report = RunReport(
        base_url="https://api.example.test",
        results=[
            ApiTestResult(
                case_id="order-500",
                title="Create order",
                status="failed",
                duration_ms=3,
                expected_status=201,
                actual_status=500,
                error="expected HTTP 201, got HTTP 500",
                evidence_refs=["order-500.actual_status"],
            )
        ],
        root_causes=[
            RootCauseCandidate(
                cause_id="cause-order-500",
                category="product_logic",
                hypothesis="Order persistence may fail when inventory is empty.",
                confidence="medium",
                case_ids=["order-500"],
                evidence_refs=["order-500.actual_status"],
                reasoning_summary="The endpoint returned 500 instead of the documented status.",
                next_checks=["Inspect the inventory service response."],
            )
        ],
    )

    html = render_html_report(report)
    payload = report.model_dump(mode="json")

    assert payload["schema_version"] == "1.0"
    assert payload["root_causes"][0]["evidence_refs"] == ["order-500.actual_status"]
    assert "Order persistence may fail" in html
    assert "order-500.actual_status" in html
    assert "Inspect the inventory service response." in html


class _InputPauseServices:
    def generate_functional(self, state: WorkflowState) -> dict:
        if state.get("input_answers"):
            return {"stage": "functional_review_required"}
        return {
            "stage": "input_required",
            "input_resume_stage": "generating_functional",
            "pending_inputs": [
                {"request_id": "token", "field": "token", "prompt": "Configure a token"}
            ],
        }

    def generate_api(self, state: WorkflowState) -> dict:
        return {"stage": "api_review_required"}

    def analyze_auth(self, state: WorkflowState) -> dict:
        return {"stage": "api_approved"}

    def generate_script(self, state: WorkflowState) -> dict:
        return {"stage": "script_review_required"}

    def run_tests(self, state: WorkflowState) -> dict:
        return {"stage": "completed"}


def test_workflow_pauses_and_resumes_with_secret_reference_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LINGTEST_TOKEN", "never-store-this-token")
    with WorkflowEngine(tmp_path / "sessions.sqlite3", services=_InputPauseServices()) as engine:
        state = engine.start({"project_root": str(tmp_path)}, thread_id="input-session")
        assert state["stage"] == "input_required"

        state = engine.resume(
            "input-session", {"answers": {"token": {"env_var": "LINGTEST_TOKEN"}}}
        )
        saved = json.dumps(engine.current_state("input-session"))

    assert state["stage"] == "functional_review_required"
    assert "never-store-this-token" not in saved
    assert state["input_answers"]["token"] == {"env_var": "LINGTEST_TOKEN"}
    assert state["input_resolution_records"][0]["secret"] is True


class _ArtifactServices(_InputPauseServices):
    def __init__(self, artifact: Path) -> None:
        self.artifact = artifact
        self.api_calls = 0

    def generate_functional(self, state: WorkflowState) -> dict:
        self.artifact.write_text("reviewed version", encoding="utf-8")
        return {
            "stage": "functional_review_required",
            "artifacts": [str(self.artifact)],
        }

    def generate_api(self, state: WorkflowState) -> dict:
        self.api_calls += 1
        return {"stage": "api_review_required"}


def test_workflow_rejects_approval_when_reviewed_artifact_changes(tmp_path) -> None:
    artifact = tmp_path / "functional-cases.html"
    services = _ArtifactServices(artifact)
    with WorkflowEngine(tmp_path / "sessions.sqlite3", services=services) as engine:
        state = engine.start({"project_root": str(tmp_path)}, thread_id="stale-session")
        assert state["stage"] == "functional_review_required"
        artifact.write_text("changed after review", encoding="utf-8")

        state = engine.resume("stale-session", "approve")

    assert state["stage"] == "failed"
    assert state["approval_decision"] == "stale"
    assert services.api_calls == 0
