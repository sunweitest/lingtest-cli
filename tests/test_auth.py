import ast
import json

import yaml

from lingtest.auth.example_parser import analyze_auth_example
from lingtest.auth.generator import write_auth_plan, write_test_script
from lingtest.auth.hook import validate_auth_hook
from lingtest.models import TestCase as ApiTestCase


def test_bearer_example_is_parsed_without_execution(tmp_path) -> None:
    marker = tmp_path / "must-not-exist"
    example = tmp_path / "auth_example.py"
    example.write_text(
        f'''
import os
from pathlib import Path
import httpx

Path(r"{marker}").write_text("executed")

def build_authenticated_client(base_url):
    client = httpx.Client(base_url=base_url)
    response = client.post(
        "/api/login",
        json={{
            "username": os.environ["TEST_USERNAME"],
            "password": os.environ["TEST_PASSWORD"],
        }},
    )
    token = response.json()["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {{token}}"
    return client
''',
        encoding="utf-8",
    )

    plan = analyze_auth_example(example, project_root=tmp_path)

    assert not marker.exists()
    assert plan.kind == "bearer"
    assert plan.login is not None and plan.login.path == "/api/login"
    assert plan.login.body["username"] == "${TEST_USERNAME}"
    assert plan.extract is not None and plan.extract.json_path == "data.access_token"
    assert plan.apply is not None and plan.apply.template == "Bearer {token}"
    assert plan.confidence == "high"


def test_cookie_session_example_is_detected(tmp_path) -> None:
    example = tmp_path / "cookie.py"
    example.write_text(
        """
import os
import httpx

def client(base_url):
    session = httpx.Client(base_url=base_url)
    session.post("/login", data={"account": os.getenv("TEST_ACCOUNT"), "password": "bad"})
    return session
""",
        encoding="utf-8",
    )

    plan = analyze_auth_example(example, project_root=tmp_path)

    assert plan.kind == "cookie"
    assert plan.login is not None and plan.login.content_type == "form"
    assert plan.login.body["password"] == "${TEST_PASSWORD}"
    assert "TEST_PASSWORD" in plan.required_env
    assert any("literal" in warning for warning in plan.warnings)


def test_auth_plan_and_generated_script_contain_no_secret(tmp_path) -> None:
    example = tmp_path / "auth.py"
    example.write_text(
        """
import httpx
client = httpx.Client()
response = client.post("/login", json={"password": "actual-secret"})
token = response.json()["token"]
client.headers["Authorization"] = f"Bearer {token}"
""",
        encoding="utf-8",
    )
    plan = analyze_auth_example(example, project_root=tmp_path)
    plan_path = tmp_path / "auth-plan.yaml"
    script_path = tmp_path / "test_api.py"
    write_auth_plan(plan, plan_path)
    write_test_script(
        [
            ApiTestCase(
                id="health", title="Health", method="GET", path="/health", expected_status=200
            )
        ],
        script_path,
        auth_plan=plan,
    )

    plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    source = script_path.read_text(encoding="utf-8")

    assert "actual-secret" not in json.dumps(plan_data)
    assert "actual-secret" not in source
    assert "_build_authenticated_client" in source
    ast.parse(source)


def test_trusted_hook_is_validated_but_not_imported(tmp_path) -> None:
    marker = tmp_path / "hook-ran"
    hook = tmp_path / "auth_hook.py"
    hook.write_text(
        f'''
from pathlib import Path
Path(r"{marker}").write_text("imported")

def sign_request(request):
    request.headers["X-Signature"] = "computed"
''',
        encoding="utf-8",
    )

    validated = validate_auth_hook("auth_hook.py:sign_request", project_root=tmp_path)

    assert validated.function == "sign_request"
    assert len(validated.sha256) == 64
    assert not marker.exists()
