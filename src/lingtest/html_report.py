# ruff: noqa: E501
"""Render self-contained, observable HTML run reports."""

import html
import json
from pathlib import Path

from lingtest.models import RunReport


def write_html_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html_report(report), encoding="utf-8")


def render_html_report(report: RunReport) -> str:
    cards = "".join(_result_card(result) for result in report.results)
    total = len(report.results)
    executed = total - report.blocked - report.skipped
    pass_rate = (report.passed / executed * 100) if executed else 0
    duration = sum(result.duration_ms for result in report.results)
    requirement_ids = {ref for result in report.results for ref in result.requirement_refs}
    executed_requirement_ids = {
        ref
        for result in report.results
        if result.status not in {"blocked", "skipped"}
        for ref in result.requirement_refs
    }
    passed_requirement_ids = {
        ref
        for result in report.results
        if result.status == "passed"
        for ref in result.requirement_refs
    }
    unlinked_cases = sum(not result.requirement_refs for result in report.results)
    root_causes = "".join(_root_cause_card(item) for item in report.root_causes)
    if not root_causes:
        message = {
            "not_requested": "未请求根因分析。可使用 lingtest run --diagnose 或 lingtest diagnose。",
            "failed": f"根因分析未完成：{html.escape(report.diagnosis_error or '未知诊断错误')}",
            "completed": "没有足够证据形成根因候选。",
        }.get(report.diagnosis_status, "未生成根因候选。")
        root_causes = f'<p class="muted">{message}</p>'
    worktree = (
        "dirty"
        if report.working_tree_dirty
        else "clean"
        if report.working_tree_dirty is False
        else "unknown"
    )
    approval_rows = (
        "".join(
            "<li>"
            f"{html.escape(item.action)}: {html.escape(item.decision)} · "
            f"{html.escape(item.decided_at.isoformat() if item.decided_at else 'time unknown')}"
            "</li>"
            for item in report.approvals
        )
        or "<li>无人工审批记录</li>"
    )
    input_rows = (
        "".join(
            "<li>"
            f"{html.escape(item.request_id)} · "
            f"{'secret reference' if item.secret else 'non-secret input'} · "
            f"{html.escape(item.env_var or 'value not retained')} · "
            f"{html.escape(item.answered_at.isoformat())}"
            "</li>"
            for item in report.input_resolutions
        )
        or "<li>无输入补充记录</li>"
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LingTest API 测试报告</title>
<style>
:root{{--ink:#14211d;--muted:#65716d;--line:#dce5e1;--brand:#087f5b;--pass:#0f9f6e;
--fail:#e5484d;--error:#d97706;--soft:#f4f7f6;--paper:#fff;--code:#18212b}}
*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);background:var(--soft);
font:15px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
header,main,footer{{width:min(1160px,calc(100% - 40px));margin:auto}}header{{padding:46px 0 22px}}
h1{{margin:0;font-size:clamp(34px,6vw,54px)}}.subtitle{{color:var(--muted);font-size:17px}}
.metrics{{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;margin:24px 0}}
.metric{{padding:18px;background:var(--paper);border:1px solid var(--line);border-radius:12px}}
.metric b{{display:block;font-size:28px}}.metric span{{color:var(--muted)}}.pass b{{color:var(--pass)}}
.fail b{{color:var(--fail)}}.error b{{color:var(--error)}}.toolbar{{display:flex;gap:8px;
margin:20px 0;flex-wrap:wrap}}button{{padding:8px 13px;border:1px solid var(--line);border-radius:8px;
background:white;cursor:pointer}}button:hover{{border-color:var(--brand);color:var(--brand)}}
details{{margin:12px 0;background:white;border:1px solid var(--line);border-radius:10px;overflow:hidden}}
details[open]{{box-shadow:0 10px 28px #17382b12}}summary{{display:grid;
grid-template-columns:90px minmax(0,1fr) 105px 100px;gap:14px;align-items:center;padding:17px;
cursor:pointer;list-style:none}}summary::-webkit-details-marker{{display:none}}.badge{{width:max-content;
padding:4px 9px;border-radius:999px;color:white;font-size:12px;font-weight:750}}.badge.passed{{background:var(--pass)}}
.badge.failed{{background:var(--fail)}}.badge.error{{background:var(--error)}}.badge.blocked,.badge.skipped{{background:#667085}}.case-id{{color:var(--muted);
font-family:ui-monospace,monospace}}.detail{{padding:4px 18px 20px;border-top:1px solid var(--line)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}pre{{overflow:auto;margin:8px 0;padding:14px;
color:#e8eef2;background:var(--code);border-radius:8px;white-space:pre-wrap;word-break:break-word}}
.error-text{{padding:12px;background:#fff1f1;border-left:4px solid var(--fail)}}footer{{padding:28px 0 40px;
color:var(--muted)}}.diagnosis{{padding:18px;margin:20px 0;background:white;border:1px solid var(--line);border-radius:12px}}
.cause{{padding:14px;margin:10px 0;background:var(--soft);border:1px solid var(--line);border-radius:8px}}
.cause h3{{margin:0 0 6px}}.muted{{color:var(--muted)}}@media(max-width:980px){{.metrics{{grid-template-columns:repeat(4,1fr)}}}}
@media(max-width:780px){{.metrics{{grid-template-columns:1fr 1fr}}summary{{grid-template-columns:
80px 1fr}}summary .duration,summary .status-code{{display:none}}.grid{{display:block}}}}
</style></head><body><header><h1>API 测试报告</h1>
<p class="subtitle">{html.escape(report.base_url)} · {html.escape(report.started_at.isoformat())} · revision {html.escape(report.revision or 'unknown')} · worktree {worktree}</p>
<section class="metrics"><div class="metric"><b>{total}</b><span>总用例</span></div>
<div class="metric pass"><b>{report.passed}</b><span>成功</span></div>
<div class="metric fail"><b>{report.failed}</b><span>失败</span></div>
<div class="metric error"><b>{report.errors}</b><span>错误</span></div>
<div class="metric"><b>{report.blocked}</b><span>阻塞</span></div>
<div class="metric"><b>{report.skipped}</b><span>跳过</span></div>
<div class="metric"><b>{pass_rate:.1f}%</b><span>通过率 · {duration:.0f} ms</span></div></section>
</header><main><section class="diagnosis"><h2>需求追踪</h2>
<p>共关联 {len(requirement_ids)} 项需求；{len(executed_requirement_ids)} 项至少执行一次，
{len(passed_requirement_ids)} 项至少有一个场景通过，{len(requirement_ids) - len(executed_requirement_ids)} 项尚未执行；
{unlinked_cases} 个用例没有需求引用。</p>
<h2>审批记录</h2><ul>{approval_rows}</ul>
<h2>输入补充记录</h2><ul>{input_rows}</ul>
<h2>预估 Bug 根因</h2>{root_causes}</section><div class="toolbar"><button onclick="filterCases('all')">全部</button>
<button onclick="filterCases('passed')">成功</button><button onclick="filterCases('failed')">失败</button>
<button onclick="filterCases('error')">错误</button><button onclick="filterCases('blocked')">阻塞</button>
<button onclick="filterCases('skipped')">跳过</button></div><section id="results">{cards}</section></main>
<footer>Generated by LingTest CLI · 敏感请求头已隐藏</footer>
<script>function filterCases(status){{document.querySelectorAll('details[data-status]').forEach(function(item){{
item.style.display=status==='all'||item.dataset.status===status?'block':'none';}});}}</script>
</body></html>"""


def _root_cause_card(candidate) -> str:
    case_ids = (
        "、".join(
            f'<a href="#{html.escape(value, quote=True)}">{html.escape(value)}</a>'
            for value in candidate.case_ids
        )
        or "未关联用例"
    )
    evidence_items = []
    for reference in candidate.evidence_refs:
        linked_case = next(
            (case_id for case_id in candidate.case_ids if reference.startswith(case_id + ".")),
            None,
        )
        rendered = html.escape(reference)
        if linked_case:
            rendered = f'<a href="#{html.escape(linked_case, quote=True)}">{rendered}</a>'
        evidence_items.append(rendered)
    evidence = "、".join(evidence_items) or "未提供"
    locations = []
    for location in candidate.code_locations:
        line = ""
        if location.line_start is not None:
            line = f":{location.line_start}"
            if location.line_end and location.line_end != location.line_start:
                line += f"-{location.line_end}"
        symbol = f" · {html.escape(location.symbol)}" if location.symbol else ""
        locations.append(f"<li><code>{html.escape(location.path + line)}</code>{symbol}</li>")
    checks = "".join(f"<li>{html.escape(value)}</li>" for value in candidate.next_checks)
    reasoning = (
        f"<p>{html.escape(candidate.reasoning_summary)}</p>" if candidate.reasoning_summary else ""
    )
    location_list = f"<ul>{''.join(locations)}</ul>" if locations else "<p>未提供源码位置</p>"
    check_list = f"<h4>下一步验证</h4><ul>{checks}</ul>" if checks else ""
    return f"""<article class="cause">
<h3>{html.escape(candidate.hypothesis)}</h3>
<p><strong>类别：</strong>{html.escape(candidate.category)} ·
<strong>置信度：</strong>{html.escape(candidate.confidence)} ·
<strong>状态：</strong>{html.escape(candidate.status)}</p>
<p><strong>关联用例：</strong>{case_ids}</p>
<p><strong>证据引用：</strong>{evidence}</p>
{reasoning}<h4>可能相关代码</h4>{location_list}{check_list}
</article>"""


def _result_card(result) -> str:
    request = {
        "method": result.method,
        "path": result.path,
        "requires_auth": result.requires_auth,
        "user_role": result.user_role,
        "data_prerequisites": result.data_prerequisites,
        "data_setup": result.data_setup,
        "data_cleanup": result.data_cleanup,
        "data_ready": result.data_ready,
        "headers": result.request_headers,
        "query": result.query,
        "body": result.request_body,
    }
    response = {
        "status": result.actual_status,
        "headers": result.response_headers,
        "body": result.response_body,
    }
    error = f'<p class="error-text">{html.escape(result.error)}</p>' if result.error else ""
    logs = "\n".join(result.logs) if result.logs else "No additional logs."
    steps = "".join(f"<li>{html.escape(step)}</li>" for step in result.steps)
    step_section = f"<h3>步骤</h3><ol>{steps}</ol>" if steps else ""
    requirements = "、".join(html.escape(item) for item in result.requirement_refs) or "未关联"
    return f"""<details id="{html.escape(result.case_id, quote=True)}" data-status="{result.status}"><summary>
<span class="badge {result.status}">{result.status.upper()}</span>
<span><strong>{html.escape(result.title)}</strong><br>
<span class="case-id">{html.escape(result.case_id)}</span></span>
<span class="status-code">HTTP {result.actual_status or "—"}</span>
<span class="duration">{result.duration_ms:.1f} ms</span></summary>
<div class="detail">{error}<p><strong>预期：</strong>HTTP {result.expected_status} · {html.escape(result.expected_result)}
<br><strong>需求引用：</strong>{requirements} · <strong>鉴权：</strong>{'是' if result.requires_auth else '否'}</p>
{step_section}<div class="grid"><section><h3>请求</h3>
<pre>{html.escape(json.dumps(request, ensure_ascii=False, indent=2))}</pre></section>
<section><h3>响应</h3><pre>{html.escape(json.dumps(response, ensure_ascii=False, indent=2))}</pre></section>
</div><h3>执行日志</h3><pre>{html.escape(logs)}</pre></div></details>"""
