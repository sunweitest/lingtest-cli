"""JUnit export with separate failure and execution-error accounting."""

from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from lingtest.models import RunReport


def write_junit(report: RunReport, path: Path) -> None:
    suite = Element(
        "testsuite",
        name="lingtest",
        tests=str(len(report.results)),
        failures=str(report.failed),
        errors=str(report.errors),
    )
    for result in report.results:
        case = SubElement(
            suite,
            "testcase",
            name=result.title,
            classname=result.case_id,
            time=f"{result.duration_ms / 1000:.6f}",
        )
        if result.status == "failed":
            failure = SubElement(case, "failure", message=result.error or result.status)
            failure.text = result.error or ""
        elif result.status == "error":
            error = SubElement(case, "error", message=result.error or result.status)
            error.text = result.error or ""
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
