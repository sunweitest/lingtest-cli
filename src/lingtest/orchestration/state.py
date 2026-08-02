"""Typed state shared by LangGraph workflow nodes."""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import TypedDict

WorkflowStage = Literal[
    "idle",
    "generating_functional",
    "functional_review_required",
    "functional_approved",
    "generating_api_cases",
    "api_review_required",
    "api_approved",
    "analyzing_auth_example",
    "auth_review_required",
    "generating_script",
    "script_review_required",
    "run_approval_required",
    "running",
    "completed",
    "rejected",
    "failed",
    "interrupted",
]


class WorkflowState(TypedDict, total=False):
    session_id: str
    stage: WorkflowStage
    trust_mode: str
    project_root: str
    document_path: str
    functional_output: str
    interface_document: str
    functional_cases: str
    api_cases_output: str
    strategy: str
    provider: str
    provider_config: str
    model: str
    base_url_override: str
    language: str
    auth_example: str
    auth_plan_mode: str
    auth_plan_output: str
    script_output: str
    target_base_url: str
    report_output: str
    cases_count: int
    dangerous_methods: list[str]
    artifacts: list[str]
    auth_plan: dict[str, Any]
    approval_action: str
    approval_decision: str
    error: str
