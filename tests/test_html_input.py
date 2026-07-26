from lingtest.document_loader import read_document


def test_html_loader_skips_style_and_script(tmp_path) -> None:
    path = tmp_path / "review.html"
    path.write_text(
        """<style>.secret { color: red }</style>
        <h1>Reviewed case</h1>
        <script>doNotSendToModel()</script>
        <p>Expected HTTP 200</p>""",
        encoding="utf-8",
    )

    content = read_document(path)

    assert "Reviewed case" in content
    assert "Expected HTTP 200" in content
    assert "color: red" not in content
    assert "doNotSendToModel" not in content
