from openpyxl import load_workbook

from lingtest.ai.models import GeneratedTestCase
from lingtest.ai.models import TestCasePlan as ReviewPlan
from lingtest.exporters import write_test_plan


def _plan() -> ReviewPlan:
    return ReviewPlan(
        summary="登录功能覆盖",
        risks=["未定义锁定策略"],
        test_cases=[
            GeneratedTestCase(
                id="login-valid",
                title="正常登录",
                case_type="functional",
                priority="P0",
                preconditions=["用户已注册"],
                steps=["输入账号密码", "点击登录"],
                expected_result="进入首页",
                source_requirement="PRD-LOGIN-1",
            )
        ],
    )


def test_review_exports_markdown_html_and_xlsx(tmp_path) -> None:
    markdown = tmp_path / "cases.md"
    html = tmp_path / "cases.html"
    xlsx = tmp_path / "cases.xlsx"

    for path in (markdown, html, xlsx):
        write_test_plan(_plan(), path)

    assert "正常登录" in markdown.read_text(encoding="utf-8")
    assert "功能测试用例" in html.read_text(encoding="utf-8")
    workbook = load_workbook(xlsx, read_only=True)
    try:
        assert workbook["功能测试用例"]["B2"].value == "正常登录"
        assert workbook["概览"]["B2"].value == 1
    finally:
        workbook.close()
