"""Explicit LingTest StateGraph whose nodes call framework-independent services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from lingtest.ai.provider import create_provider
from lingtest.ai.service import diagnose_failures
from lingtest.artifacts import (
    read_case_bundle_with_inputs,
    write_cases,
    write_test_script,
)
from lingtest.auth.example_parser import analyze_auth_example
from lingtest.auth.generator import write_auth_plan
from lingtest.auth.models import AuthPlan
from lingtest.auth.openapi import analyze_openapi_auth
from lingtest.auth.planner import create_auth_plan
from lingtest.exporters import write_test_plan
from lingtest.html_report import write_html_report
from lingtest.io import write_report
from lingtest.observable_runner import run_cases
from lingtest.openapi import generate_cases
from lingtest.orchestration.event_adapter import redact_text
from lingtest.orchestration.inputs import normalize_requests, sanitize_answers
from lingtest.orchestration.permissions import (
    assert_non_negotiable_scope,
    requires_approval,
)
from lingtest.orchestration.state import WorkflowState
from lingtest.prd_workflow import generate_functional_plan
from lingtest.source_context import collect_source_context
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
        plan = generate_functional_plan(
            document,
            provider,
            language=state.get("language", "zh-CN"),
            context_answers=state.get("input_answers"),
        )
        write_test_plan(plan, Path(output))
        answered = state.get("input_answers", {})
        requests = normalize_requests(
            [item for item in plan.input_requests if item.request_id not in answered]
        )
        return {
            "stage": "input_required" if requests else "functional_review_required",
            "functional_cases": output,
            "cases_count": len(plan.test_cases),
            "pending_inputs": requests,
            "input_resume_stage": "generating_functional",
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
                context_answers=state.get("input_answers"),
            )
            cases = to_executable_cases(
                plan,
                deterministic_cases=seeds if strategy == "auto" else None,
                auth_seeds=seeds,
            )
            answered = state.get("input_answers", {})
            requests = normalize_requests(
                [item for item in plan.input_requests if item.request_id not in answered]
            )
        if strategy == "deterministic":
            requests = []
        write_cases(cases, Path(output), input_requests=requests)
        dangerous = sorted({case.method.upper() for case in cases} - {"GET", "HEAD", "OPTIONS"})
        return {
            "stage": "input_required" if requests else "api_review_required",
            "api_cases_output": output,
            "cases_count": len(cases),
            "pending_inputs": requests,
            "input_resume_stage": "generating_api_cases",
            "dangerous_methods": dangerous,
            "artifacts": _artifacts(state, output),
        }

    def analyze_auth(self, state: WorkflowState) -> dict[str, Any]:
        example = state.get("auth_example")
        interface = state.get("interface_document")
        auth_document = state.get("auth_document")
        if example:
            plan = analyze_auth_example(example, project_root=_root(state))
        elif auth_document:
            plan = create_auth_plan(
                interface or auth_document,
                auth_document=auth_document if interface else None,
                provider=_provider(state),
                project_root=_root(state),
            )
        elif interface and Path(interface).suffix.lower() in {".json", ".yaml", ".yml"}:
            try:
                plan = analyze_openapi_auth(interface, project_root=_root(state))
            except ValueError:
                # The interface may be an unstructured YAML document rather than OpenAPI.
                plan = None
        else:
            plan = None
        if plan is None:
            return {"stage": "api_approved"}
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
        cases, embedded_plan, input_requests = read_case_bundle_with_inputs(cases_file)
        if any(request.required for request in input_requests):
            raise ValueError("Required input requests remain unresolved in the API case bundle")
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
        cases, embedded_plan, input_requests = read_case_bundle_with_inputs(
            Path(_required(state, "api_cases_output"))
        )
        raw_plan = state.get("auth_plan")
        plan = AuthPlan.model_validate(raw_plan) if raw_plan else embedded_plan
        report = run_cases(
            cases,
            _required(state, "target_base_url"),
            auth_plan=plan,
            auth_hook=plan.hook if plan else None,
            project_root=_root(state),
            input_requests=input_requests,
            approval_records=state.get("approval_records", []),
            input_resolutions=state.get("input_resolution_records", []),
            event_callback=lambda event_type, data: _emit_workflow_event(
                event_type, {"stage": "running", **data}
            ),
        )
        if state.get("diagnose"):
            report.diagnosis_status = "completed"
            if report.failed or report.errors:
                try:
                    source_root = state.get("source_root")
                    context = (
                        collect_source_context(
                            report,
                            source_root,
                            hints=state.get("context_hints"),
                        )
                        if source_root
                        else None
                    )
                    if context is not None:
                        report.mode = "code-aware"
                    diagnosis = diagnose_failures(
                        report,
                        _provider(state),
                        language=state.get("language", "zh-CN"),
                        source_context=context,
                    )
                    report.root_causes = diagnosis.root_causes
                    _emit_workflow_event(
                        "diagnosis_created",
                        {
                            "stage": "running",
                            "root_causes": [item.cause_id for item in report.root_causes],
                        },
                    )
                except Exception:
                    report.diagnosis_status = "failed"
                    report.diagnosis_error = (
                        "Root-cause analysis failed; the API execution results were preserved."
                    )
        output = _output(state, "report_output", "lingtest-report.html")
        assert_non_negotiable_scope(project_root=str(_root(state)), target_path=output)
        if Path(output).suffix.lower() in {".html", ".htm"}:
            write_html_report(report, Path(output))
        else:
            write_report(report, Path(output))
        execution_issue = report.failed or report.errors or report.blocked
        return {
            "stage": "failed" if execution_issue else "completed",
            "report_output": output,
            "artifacts": _artifacts(state, output),
            "error": (
                f"{report.failed} failures, {report.errors} execution errors, "
                f"{report.blocked} blocked cases"
                if execution_issue
                else ""
            ),
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
    builder.add_node("request_inputs", _request_inputs)
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
        "generate_functional",
        _route_generation,
        {"input": "request_inputs", "review": "review_functional", "end": END},
    )
    builder.add_conditional_edges(
        "review_functional", _next_or_end, {"next": "generate_api", "end": END}
    )
    builder.add_conditional_edges(
        "generate_api",
        _route_generation,
        {"input": "request_inputs", "review": "review_api", "end": END},
    )
    builder.add_conditional_edges(
        "request_inputs",
        _route_input_resume,
        {"functional": "generate_functional", "api": "generate_api", "end": END},
    )
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
    internal_fields = {
        "auth_plan",
        "approval_action",
        "approval_decision",
        "approval_records",
        "approval_artifact_sha256",
        "input_answers",
        "input_resolution_records",
        "pending_inputs",
        "input_resume_stage",
    }
    supplied_internal = sorted(internal_fields.intersection(values))
    if supplied_internal:
        raise ValueError(
            "Workflow configuration cannot set internal state fields: "
            + ", ".join(supplied_internal)
        )
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
        _emit_workflow_event("stage_started", {"stage": running_stage})
        try:
            update = callback({**state, "stage": running_stage})
            _emit_workflow_event(
                "stage_completed",
                {
                    "stage": update.get("stage", running_stage),
                    "artifacts": update.get("artifacts", []),
                },
            )
            return update
        except Exception as exc:
            safe_error = redact_text(str(exc))
            _emit_workflow_event("workflow_failed", {"stage": running_stage, "error": safe_error})
            return {"stage": "failed", "error": safe_error}

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
        artifact_sha256 = _artifact_digests(state.get("artifacts", []))
        decision = interrupt(
            {
                "action": action,
                "stage": state.get("stage"),
                "artifacts": state.get("artifacts", []),
                "artifact_sha256": artifact_sha256,
                "target_base_url": state.get("target_base_url"),
                "dangerous_methods": state.get("dangerous_methods", []),
            }
        )
        value = decision.get("decision") if isinstance(decision, dict) else decision
        approved = str(value).lower() in {"approve", "approved", "yes"}
        if approved and (
            not isinstance(decision, dict) or decision.get("artifact_sha256") != artifact_sha256
        ):
            return {
                "stage": "failed",
                "approval_action": action,
                "approval_decision": "stale",
                "error": (
                    f"Artifact content changed after approval was requested for {action}; "
                    "review the updated artifacts and resume from a new workflow."
                ),
            }
        decided_at = datetime.now(UTC).isoformat()
        decision_label = "approved" if approved else "rejected"
        record = {
            "action": action,
            "decision": decision_label,
            "decided_at": decided_at,
            "artifact_sha256": artifact_sha256,
        }
        records = [*state.get("approval_records", []), record]
        if not approved:
            return {
                "stage": "rejected",
                "approval_action": action,
                "approval_decision": str(value),
                "approval_records": records,
                "approval_artifact_sha256": artifact_sha256,
                "error": f"Action {action} was rejected",
            }
        return {
            "stage": approved_stage,
            "approval_action": action,
            "approval_decision": "approved",
            "approval_records": records,
            "approval_artifact_sha256": artifact_sha256,
        }

    return node


def _next_or_end(state: WorkflowState) -> str:
    return "end" if state.get("stage") in {"failed", "rejected"} else "next"


def _route_generation(state: WorkflowState) -> str:
    if state.get("stage") in {"failed", "rejected"}:
        return "end"
    return "input" if state.get("stage") == "input_required" else "review"


def _route_input_resume(state: WorkflowState) -> str:
    if state.get("stage") == "generating_functional":
        return "functional"
    if state.get("stage") == "generating_api_cases":
        return "api"
    return "end"


def _request_inputs(state: WorkflowState) -> dict[str, Any]:
    requests = normalize_requests(state.get("pending_inputs", []))
    if not requests:
        return {"stage": "failed", "error": "No pending input requests were found"}
    resume_value = interrupt(
        {
            "action": "provide_inputs",
            "stage": "input_required",
            "session_id": state.get("session_id"),
            "requests": requests,
        }
    )
    if not isinstance(resume_value, dict) or "answers" not in resume_value:
        raise ValueError("Resume input must contain an answers object keyed by request_id")
    answers = sanitize_answers(requests, resume_value["answers"])
    request_by_id = {item["request_id"]: item for item in requests}
    answered_at = datetime.now(UTC).isoformat()
    resolutions = []
    for request_id, value in answers.items():
        request = request_by_id[request_id]
        secret = bool(request.get("secret") or request.get("type") == "secret")
        resolutions.append(
            {
                "request_id": request_id,
                "secret": secret,
                "env_var": value.get("env_var") if secret and isinstance(value, dict) else None,
                "answered_at": answered_at,
            }
        )
    return {
        "stage": state.get("input_resume_stage", "failed"),
        "input_answers": {**state.get("input_answers", {}), **answers},
        "pending_inputs": [],
        "input_resolution_records": [
            *state.get("input_resolution_records", []),
            *resolutions,
        ],
    }


def _emit_workflow_event(event_type: str, data: dict[str, Any]) -> None:
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except (ImportError, LookupError, RuntimeError):
        return
    writer({"type": event_type, "data": data})


def _artifact_digests(artifacts: list[str]) -> dict[str, str | None]:
    digests: dict[str, str | None] = {}
    for item in artifacts:
        path = Path(item)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            digest = None
        except OSError as exc:
            raise ValueError(f"Cannot verify approval artifact {path}: {exc}") from exc
        digests[str(path)] = digest
    return digests


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
