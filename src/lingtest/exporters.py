# ruff: noqa: E501
"""Export AI-generated test plans for human review."""

import html
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from lingtest.ai.models import TestCasePlan


def write_test_plan(plan: TestCasePlan, path: Path) -> None:
    """Write a reviewable test plan based on the output suffix."""
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    elif suffix in {".yaml", ".yml"}:
        path.write_text(
            yaml.safe_dump(
                plan.model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    elif suffix == ".md":
        path.write_text(_plan_markdown(plan), encoding="utf-8")
    elif suffix in {".html", ".htm"}:
        path.write_text(_plan_html(plan), encoding="utf-8")
    elif suffix == ".xlsx":
        _plan_xlsx(plan, path)
    else:
        raise ValueError("Test plan output must be .json, .yaml, .md, .html, or .xlsx")


def _plan_markdown(plan: TestCasePlan) -> str:
    lines = [
        "# 功能测试用例",
        "",
        f"> {plan.summary}",
        "",
        "## 风险",
        "",
        *([f"- {risk}" for risk in plan.risks] or ["- 暂无"]),
        "",
        "## 待补充信息",
        "",
        *(
            [f"- `{item.request_id}`（{item.type}）：{item.prompt}" for item in plan.input_requests]
            or ["- 暂无"]
        ),
        "",
        "## 测试用例",
        "",
    ]
    for case in plan.test_cases:
        lines.extend(
            [
                f"### {case.id} · {case.title}",
                "",
                f"- 类型：`{case.case_type}`",
                f"- 优先级：`{case.priority}`",
                f"- 来源需求：{case.source_requirement or '未标注'}",
                f"- 需求引用：{', '.join(case.requirement_refs) or '未标注'}",
                f"- 前置条件：{'；'.join(case.preconditions) or '无'}",
                f"- 用户角色：{case.user_role or '未指定'}",
                f"- 数据前置：{'；'.join(case.data_prerequisites) or '无'}",
                f"- 数据准备：{'；'.join(case.data_setup) or '无'}",
                f"- 数据清理：{'；'.join(case.data_cleanup) or '无'}",
                "",
                "步骤：",
                "",
                *[f"{index}. {step}" for index, step in enumerate(case.steps, 1)],
                "",
                f"预期结果：{case.expected_result}",
                "",
            ]
        )
    return "\n".join(lines)


def _plan_html(plan: TestCasePlan) -> str:
    cards = []
    for case in plan.test_cases:
        steps = "".join(f"<li>{html.escape(step)}</li>" for step in case.steps)
        preconditions = "".join(f"<li>{html.escape(item)}</li>" for item in case.preconditions)
        data_requirements = "".join(
            f"<li>{html.escape(item)}</li>" for item in case.data_prerequisites
        )
        setup = "".join(f"<li>{html.escape(item)}</li>" for item in case.data_setup)
        cleanup = "".join(f"<li>{html.escape(item)}</li>" for item in case.data_cleanup)
        cards.append(
            f"""
            <article class="case">
              <div class="case-head">
                <div><span class="id">{html.escape(case.id)}</span>
                  <h2>{html.escape(case.title)}</h2></div>
                <div><span class="tag">{html.escape(case.case_type)}</span>
                  <span class="priority">{html.escape(case.priority)}</span></div>
              </div>
              <p class="source">来源：{html.escape(case.source_requirement or "未标注")}</p>
              <p class="source">需求引用：{html.escape(", ".join(case.requirement_refs) or "未标注")}</p>
              <p class="source">用户角色：{html.escape(case.user_role or "未指定")}</p>
              <div class="columns">
                <section><h3>前置条件</h3><ul>{preconditions or "<li>无</li>"}</ul></section>
                <section><h3>执行步骤</h3><ol>{steps}</ol></section>
              </div>
              <div class="columns">
                <section><h3>测试数据前置</h3><ul>{data_requirements or "<li>无</li>"}</ul></section>
                <section><h3>准备与清理</h3><ul>{setup}{cleanup or "<li>无清理步骤</li>"}</ul></section>
              </div>
              <div class="expected"><strong>预期结果</strong>
                <p>{html.escape(case.expected_result)}</p></div>
            </article>"""
        )
    risks = "".join(f"<li>{html.escape(risk)}</li>" for risk in plan.risks) or "<li>暂无</li>"
    input_requests = (
        "".join(
            f"<li><code>{html.escape(item.request_id)}</code> ({html.escape(item.type)}): "
            f"{html.escape(item.prompt)}</li>"
            for item in plan.input_requests
        )
        or "<li>暂无</li>"
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>功能测试用例</title>
<style>
:root{{--ink:#14211d;--muted:#66736e;--line:#dce5e1;--brand:#087f5b;--soft:#f4f7f6}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--soft);color:var(--ink);
font:15px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
header,main{{width:min(1100px,calc(100% - 40px));margin:auto}}header{{padding:52px 0 26px}}
h1{{margin:0 0 8px;font-size:clamp(34px,6vw,56px)}}.summary{{max-width:780px;color:var(--muted);
font-size:18px}}.overview{{display:grid;grid-template-columns:140px 1fr;gap:18px;margin:18px 0 28px;
padding:18px;background:white;border:1px solid var(--line);border-radius:12px}}
.count{{font-size:34px;font-weight:750;color:var(--brand)}}.case{{margin:0 0 18px;padding:24px;background:white;
border:1px solid var(--line);border-radius:12px}}.case-head{{display:flex;justify-content:space-between;
gap:20px;align-items:start}}h2{{margin:4px 0 0;font-size:22px}}h3{{font-size:15px}}.id,.source{{color:var(--muted)}}
.tag,.priority{{display:inline-block;padding:4px 9px;border-radius:999px;background:#e5f4ee;color:var(--brand);
font-size:12px;font-weight:700}}.priority{{background:#fff0e6;color:#c2410c}}.columns{{display:grid;
grid-template-columns:1fr 2fr;gap:24px}}.expected{{margin-top:18px;padding:13px 16px;background:#f0f8f5;
border-left:4px solid var(--brand);border-radius:6px}}.expected p{{margin:4px 0}}@media(max-width:700px){{
.case-head,.columns{{display:block}}.case-head>div:last-child{{margin-top:10px}}}}
</style></head><body><header><h1>功能测试用例</h1>
<p class="summary">{html.escape(plan.summary)}</p></header><main>
<section class="overview"><div><div class="count">{len(plan.test_cases)}</div>条用例</div>
<div><strong>已识别风险</strong><ul>{risks}</ul>
<strong>待补充信息</strong><ul>{input_requests}</ul></div></section>
{"".join(cards)}</main></body></html>"""


def _plan_xlsx(plan: TestCasePlan, path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "功能测试用例"
    headers = [
        "用例ID",
        "标题",
        "类型",
        "优先级",
        "来源需求",
        "需求引用",
        "前置条件",
        "步骤",
        "预期结果",
        "方法",
        "路径",
        "预期状态码",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="087F5B")
        cell.alignment = Alignment(horizontal="center")
    for case in plan.test_cases:
        sheet.append(
            [
                case.id,
                case.title,
                case.case_type,
                case.priority,
                case.source_requirement,
                ", ".join(case.requirement_refs),
                "\n".join(case.preconditions),
                "\n".join(f"{index}. {step}" for index, step in enumerate(case.steps, 1)),
                case.expected_result,
                case.method or "",
                case.path or "",
                case.expected_status or "",
            ]
        )
    widths = [20, 30, 14, 10, 30, 24, 30, 48, 40, 10, 28, 12]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    overview = workbook.create_sheet("概览")
    overview.append(["摘要", plan.summary])
    overview.append(["用例总数", len(plan.test_cases)])
    overview.append(["风险", "\n".join(plan.risks)])
    overview.column_dimensions["A"].width = 16
    overview.column_dimensions["B"].width = 90
    overview["A1"].font = Font(bold=True)
    overview["A2"].font = Font(bold=True)
    overview["A3"].font = Font(bold=True)
    overview["B3"].alignment = Alignment(wrap_text=True, vertical="top")
    workbook.save(path)
