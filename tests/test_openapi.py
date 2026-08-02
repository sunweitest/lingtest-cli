from pathlib import Path

from lingtest.openapi import generate_cases


def test_generate_cases_from_openapi(tmp_path: Path) -> None:
    spec = tmp_path / "openapi.yaml"
    spec.write_text(
        """
openapi: 3.0.0
paths:
  /users/{user_id}:
    get:
      summary: Get user
      parameters:
        - in: path
          name: user_id
          required: true
          schema: {type: integer, example: 42}
        - in: query
          name: verbose
          schema: {type: boolean, default: true}
      responses:
        "200": {description: OK}
""",
        encoding="utf-8",
    )

    cases = generate_cases(spec)

    assert len(cases) == 1
    assert cases[0].path == "/users/42"
    assert cases[0].query == {"verbose": True}
    assert cases[0].expected_status == 200
