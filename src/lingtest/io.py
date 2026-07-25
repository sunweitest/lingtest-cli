import json
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from lingtest.models import RunReport, TestCase


def write_cases(cases: list[TestCase], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([case.model_dump(mode="json") for case in cases], indent=2),
        encoding="utf-8",
    )


def read_cases(path: Path) -> list[TestCase]:
    return [TestCase.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def write_report(report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def read_report(path: Path) -> RunReport:
    return RunReport.model_validate_json(path.read_text(encoding="utf-8"))


def write_junit(report: RunReport, path: Path) -> None:
    suite = Element(
        "testsuite",
        name="lingtest",
        tests=str(len(report.results)),
        failures=str(report.failed),
    )
    for result in report.results:
        case = SubElement(
            suite,
            "testcase",
            name=result.title,
            classname=result.case_id,
            time=f"{result.duration_ms / 1000:.6f}",
        )
        if result.status != "passed":
            failure = SubElement(case, "failure", message=result.error or result.status)
            failure.text = result.error or ""
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
