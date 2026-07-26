from docx import Document
from openpyxl import Workbook

from lingtest.document_loader import read_document


def test_read_docx_paragraphs_and_tables(tmp_path) -> None:
    path = tmp_path / "prd.docx"
    document = Document()
    document.add_heading("登录需求", level=1)
    document.add_paragraph("用户可以使用账号登录。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "字段"
    table.cell(0, 1).text = "说明"
    table.cell(1, 0).text = "username"
    table.cell(1, 1).text = "用户名"
    document.save(path)

    content = read_document(path)

    assert "# 登录需求" in content
    assert "用户可以使用账号登录" in content
    assert "| 字段 | 说明 |" in content
    assert "username" in content


def test_read_xlsx_review_artifact(tmp_path) -> None:
    path = tmp_path / "cases.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "功能用例"
    sheet.append(["标题", "预期结果"])
    sheet.append(["正常登录", "进入首页"])
    workbook.save(path)

    content = read_document(path)

    assert "# Sheet: 功能用例" in content
    assert "正常登录 | 进入首页" in content
