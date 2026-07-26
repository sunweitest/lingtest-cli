from datetime import UTC, datetime
from xml.etree.ElementTree import parse

from lingtest.junit_report import write_junit
from lingtest.models import RunReport
from lingtest.models import TestResult as ApiTestResult


def test_junit_separates_failures_and_errors(tmp_path) -> None:
    report = RunReport(
        started_at=datetime.now(UTC),
        base_url="https://example.test",
        results=[
            ApiTestResult(
                case_id="failed",
                title="Failed assertion",
                status="failed",
                duration_ms=1,
                expected_status=200,
                actual_status=500,
            ),
            ApiTestResult(
                case_id="error",
                title="Connection error",
                status="error",
                duration_ms=1,
                expected_status=200,
                error="connection refused",
            ),
        ],
    )
    path = tmp_path / "junit.xml"

    write_junit(report, path)
    suite = parse(path).getroot()

    assert suite.attrib["failures"] == "1"
    assert suite.attrib["errors"] == "1"
    assert suite.find("./testcase/failure") is not None
    assert suite.find("./testcase[2]/error") is not None
