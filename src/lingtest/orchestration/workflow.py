"""Explicit LingTest StateGraph whose nodes call framework-independent services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from lingtest.ai.provider import create_provider
from lingtest.artifacts import read_case_bundle, write_cases, write_test_script
from lingtest.auth.example_parser import analyze_auth_example
from lingtest.auth.generator import write_auth_plan
from lingtest.auth.models import AuthPlan
from lingtest.exporters import write_test_plan
from lingtest.html_report import write_html_report
from lingtest.io import write_report
from lingtest.observable_runner import run_cases
from lingtest.openapi import generate_cases
from lingtest.orchestration.permissions import (
    assert_non_negotiable_scope,
    requires_approval,
)
from lingtest.orchestration.state import WorkflowState
from lingtest.prd_workflow import generate_functional_plan
from lingtest.workflow import generate_api_plan, to_executable_cases


class WorkflowServices(Protocol):
    def generate_functional(self, state: WorkflowState) -> dict[str, Any]: ...

    def generate_api(self, state: WorkflowState) -> dict[str, Any]: ...

    def analyze_auth(self, state: WorkflowState) -> dict[str, Any]: ...

    def generate_script(self, state: WorkflowState) -> dict[str, Any]: ...

    def run_tests(self, state: WorkflowState) -> dict[str, Any]: ...


@dataclass(slots=True)
class DefaultWorkflowServices:
    """Default graph nodes backed by LingTest's existing domain services."""

    def generate_functional(self, state: WorkflowState) -> dict[str, Any]:
        root = _root(state)
        document = _required(state, "document_path")
        output = _output(state, "functional_output", "functional-cases.html")
        assert_non_negotiable_scope(project_root=str(root), target_path=output)
        provider = _provider(state)
        plan = generate_functional_plan(document, provider, language=state.get("language", "zh-CN"))
        write_test_plan(plan, Path(output))
        return {
            "stage": "functional_review_required",
            "functional_cases": output,
            "cases_count": len(plan.test_cases),
            "artifacts": _artifacts(state, output),
        }

    def generate_api(self, state: WorkflowState) -> dict[str, Any]:
        root = _root(state)
        interface = _required(state, "interface_document")
        output = _output(state, "api_cases_output", "lingtest-cases.yaml")
        assert_non_negotiable_scope(project_root=str(root), target_path=output)
        strategy = state.get("strategy", "auto").lower()
        seeds = _openapi_seeds(Path(interface))
        if strategy == "deterministic":
            if not seeds:
                raise ValueError("deterministic strategy requires a valid OpenAPI document")
            cases = seeds
        else:
            plan = generate_api_plan(
                interface,
                _provider(state),
                functional_cases=state.get("functional_cases"),
                deterministic_cases=seeds if strategy == "auto" else None,
                language=state.get("language", "zh-CN"),
            )
            cases = to_executable_cases(plan)
        write_cases(cases, Path(output))
        dangerous = sorted({case.method.upper() for case in cases} - {"GET", "HEAD", "OPTIONS"})
        return {
            "stage": "api_review_required",
            "api_cases_output": output,
            "cases_count": len(cases),
            "dangerous_methods": dangerous,
            "artifacts": _artifacts(state, output),
        }

    def analyze_auth(self, state: WorkflowState) -> dict[str, Any]:
        example = state.get("auth_example")
        if not example:
            return {"stage": "api_approved"}
        plan = analyze_auth_example(example, project_root=_root(state))
        output = _output(state, "auth_plan_output", "lingtest-auth-plan.yaml")
        assert_non_negotiable_scope(project_root=str(_root(state)), target_path=output)
        write_auth_plan(plan, Path(output))
        return {
            "stage": "auth_review_required",
            "auth_plan": plan.model_dump(mode="json", exclude_none=True),
            "auth_plan_output": output,
            "artifacts": _artifacts(state, output),
        }

    def generate_script(self, state: WorkflowState) -> dict[str, Any]:
        cases_file = Path(_required(state, "api_cases_output"))
        output = _output(state, "script_output", "tests/test_lingtest_api.py")
        assert_non_negotiable_scope(project_root=str(_root(state)), target_path=output)
        cases, embedded_plan = read_case_bundle(cases_file)
        raw_plan = state.get("auth_plan")
        plan = AuthPlan.model_validate(raw_plan) if raw_plan else embedded_plan
        write_test_script(
            cases, Path(output), auth_plan=plan, auth_hook=plan.hook if plan else None
        )
        return {
            "stage": "script_review_required",
            "script_output": output,
            "artifacts": _artifacts(state, output),
        }

    def run_tests(self, state: WorkflowState) -> dict[str, Any]:
        cases, embedded_plan = read_case_bundle(Path(_required(state, "api_cases_output")))
        raw_plan = state.get("auth_plan")
        plan = AuthPlan.model_validate(raw_plan) if raw_plan else embedded_plan
        report = run_cases(
            cases,
            _required(state, "target_base_url"),
            auth_plan=plan,
            auth_hook=plan.hook if plan else None,
            project_root=_root(state),
        )
        output = _output(state, "report_output", "lingtest-report.html")
        assert_non_negotiable_scope(project_root=str(_root(state)), target_path=output)
        if Path(output).suffix.lower() in {".html", ".htm"}:
            write_html_report(report, Path(output))
        else:
            write_report(report, Path(output))
        return {
            "stage": "completed" if not report.errors else "failed",
            "report_output": output,
            "artifacts": _artifacts(state, output),
            "error": f"{report.errors} execution errors" if report.errors else "",
        }


def build_workflow(
    services: WorkflowServices,
    *,
    allowed_hosts: set[str] | None = None,
) -> StateGraph:
    builder = StateGraph(WorkflowState)
    builder.add_node(
        "generate_functional", _safe(services.generate_functional, "generating_functional")
    )
    builder.add_node("review_functional", _approval("review_functional", "functional_approved"))
    builder.add_node("generate_api", _safe(services.generate_api, "generating_api_cases"))
    builder.add_node("review_api", _approval("review_api", "api_approved"))
    builder.add_node("analyze_auth", _safe(services.analyze_auth, "analyzing_auth_example"))
    builder.add_node("review_auth", _approval("review_auth", "api_approved"))
    builder.add_node("generate_script", _safe(services.generate_script, "generating_script"))
    builder.add_node("review_script", _approval("write_script", "api_approved"))
    builder.add_node(
        "approve_run",
        _approval("run_tests", "run_approval_required", allowed_hosts=allowed_hosts),
    )
    builder.add_node("run_tests", _safe(services.run_tests, "running"))
    builder.add_node("finalize", lambda state: {"stage": "completed"})

    builder.add_edge(START, "generate_functional")
    builder.add_conditional_edges(
        "generate_functional", _next_or_end, {"next": "review_functional", "end": END}
    )
    builder.add_conditional_edges(
        "review_functional", _next_or_end, {"next": "generate_api", "end": END}
    )
    builder.add_conditional_edges("generate_api", _next_or_end, {"next": "review_api", "end": END})
    builder.add_conditional_edges("review_api", _next_or_end, {"next": "analyze_auth", "end": END})
    builder.add_conditional_edges(
        "analyze_auth",
        lambda state: (
            "review" if state.get("stage") == "auth_review_required" else _next_or_end(state)
        ),
        {"review": "review_auth", "next": "generate_script", "end": END},
    )
    builder.add_conditional_edges(
        "review_auth", _next_or_end, {"next": "generate_script", "end": END}
    )
    builder.add_conditional_edges(
        "generate_script", _next_or_end, {"next": "review_script", "end": END}
    )
    builder.add_conditional_edges(
        "review_script",
        lambda state: (
            "run" if state.get("target_base_url") and _next_or_end(state) == "next" else "complete"
        ),
        {"run": "approve_run", "complete": "finalize"},
    )
    builder.add_conditional_edges("approve_run", _next_or_end, {"next": "run_tests", "end": END})
    builder.add_edge("run_tests", END)
    builder.add_edge("finalize", END)
    return builder


def initial_state(**values: Any) -> WorkflowState:
    root = Path(values.get("project_root") or Path.cwd()).resolve()
    state: WorkflowState = {
        "stage": "idle",
        "trust_mode": str(values.get("trust_mode") or "guarded"),
        "project_root": str(root),
        "strategy": str(values.get("strategy") or "auto"),
        "provider": str(values.get("provider") or "openai"),
        "language": str(values.get("language") or "zh-CN"),
        "artifacts": [],
    }
    state.update({key: value for key, value in values.items() if value is not None})
    return state


def _safe(callback, running_stage: str):
    def node(state: WorkflowState) -> dict[str, Any]:
        try:
            update = callback({**state, "stage": running_stage})
            return update
        except Exception as exc:
            return {"stage": "failed", "error": str(exc)}

    return node


def _approval(action: str, approved_stage: str, *, allowed_hosts: set[str] | None = None):
    def node(state: WorkflowState) -> dict[str, Any]:
        needs_review = requires_approval(
            state.get("trust_mode", "guarded"),
            action,
            target_url=state.get("target_base_url"),
            allowed_hosts=allowed_hosts,
            dangerous_methods=set(state.get("dangerous_methods") or []),
        )
        if not needs_review:
            return {
                "stage": approved_stage,
                "approval_action": action,
                "approval_decision": "trusted",
            }
        decision = interrupt(
            {
                "action": action,
                "stage": state.get("stage"),
                "artifacts": state.get("artifacts", []),
                "target_base_url": state.get("target_base_url"),
                "dangerous_methods": state.get("dangerous_methods", []),
            }
        )
        value = decision.get("decision") if isinstance(decision, dict) else decision
        if str(value).lower() not in {"approve", "approved", "yes"}:
            return {
                "stage": "rejected",
                "approval_action": action,
                "approval_decision": str(value),
                "error": f"Action {action} was rejected",
            }
        return {"stage": approved_stage, "approval_action": action, "approval_decision": "approved"}

    return node


def _next_or_end(state: WorkflowState) -> str:
    return "end" if state.get("stage") in {"failed", "rejected"} else "next"


def _provider(state: WorkflowState):
    return create_provider(
        state.get("provider", "openai"),
        model=state.get("model"),
        base_url=state.get("base_url_override"),
        config_path=state.get("provider_config"),
        cwd=_root(state),
    )


def _root(state: WorkflowState) -> Path:
    return Path(state.get("project_root") or Path.cwd()).resolve()


def _required(state: WorkflowState, key: str) -> str:
    value = state.get(key)
    if not value:
        raise ValueError(f"Workflow requires {key}")
    return str(value)


def _output(state: WorkflowState, key: str, default: str) -> str:
    value = state.get(key)
    path = Path(str(value)) if value else _root(state) / default
    if not path.is_absolute():
        path = _root(state) / path
    return str(path.resolve())


def _artifacts(state: WorkflowState, item: str) -> list[str]:
    return [*state.get("artifacts", []), item]


def _openapi_seeds(path: Path):
    if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
        return []
    try:
        return generate_cases(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
