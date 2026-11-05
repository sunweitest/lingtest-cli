"""Read and write executable API datasets and generated Python scripts."""

import json
from pathlib import Path

import yaml

from lingtest.auth.generator import write_test_script as _write_test_script
from lingtest.auth.models import AuthHook, AuthPlan
from lingtest.models import InputRequest, TestCase


def read_case_bundle(path: Path) -> tuple[list[TestCase], AuthPlan | None]:
    cases, auth_plan, _ = read_case_bundle_with_inputs(path)
    return cases, auth_plan


def read_case_bundle_with_inputs(
    path: Path,
) -> tuple[list[TestCase], AuthPlan | None, list[InputRequest]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("Executable cases must be .json, .yaml, or .yml")

    auth_plan = None
    input_requests: list[InputRequest] = []
    if isinstance(data, dict):
        if "cases" not in data:
            raise ValueError("Executable case bundle must contain a cases list")
        schema_version = str(data.get("schema_version", "1.0"))
        if schema_version != "1.0":
            raise ValueError(f"Unsupported case bundle schema_version: {schema_version}")
        raw_auth = data.get("auth")
        auth_plan = AuthPlan.model_validate(raw_auth) if raw_auth else None
        input_requests = [
            InputRequest.model_validate(item) for item in data.get("input_requests", [])
        ]
        data = data["cases"]
    if not isinstance(data, list):
        raise ValueError("Executable case dataset must be a list")
    return [TestCase.model_validate(item) for item in data], auth_plan, input_requests


def read_cases(path: Path) -> list[TestCase]:
    return read_case_bundle(path)[0]


def write_cases(
    cases: list[TestCase],
    path: Path,
    *,
    auth_plan: AuthPlan | None = None,
    embed_auth: bool = False,
    input_requests: list[InputRequest | dict] | None = None,
) -> None:
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    case_data = [case.model_dump(mode="json") for case in cases]
    data = {"schema_version": "1.0", "cases": case_data}
    if input_requests:
        data["input_requests"] = [
            InputRequest.model_validate(item).model_dump(mode="json", exclude_none=True)
            for item in input_requests
        ]
    if auth_plan is not None and embed_auth:
        data["auth"] = auth_plan.model_dump(mode="json", exclude_none=True)
    if suffix == ".json":
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    elif suffix in {".yaml", ".yml"}:
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    else:
        raise ValueError("Executable case output must be .json, .yaml, or .yml")


def write_test_script(
    cases: list[TestCase],
    path: Path,
    *,
    auth_plan: AuthPlan | None = None,
    auth_hook: AuthHook | None = None,
) -> None:
    _write_test_script(cases, path, auth_plan=auth_plan, auth_hook=auth_hook)
