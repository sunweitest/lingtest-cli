import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from lingtest.ai.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(ValueError):
    """Raised when an LLM response cannot satisfy the requested schema."""


def parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = json.loads(_extract_object(text))
    if not isinstance(value, dict):
        raise StructuredOutputError("LLM response must be a JSON object")
    return value


def request_structured(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    schema: type[T],
    *,
    retries: int = 1,
) -> T:
    current = list(messages)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        raw = provider.complete(current, json_mode=True)
        try:
            return schema.model_validate(parse_json_object(raw))
        except (json.JSONDecodeError, StructuredOutputError, ValidationError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            current.extend(
                [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "The response failed schema validation. Return only a corrected JSON "
                            f"object. Validation error: {exc}"
                        ),
                    },
                ]
            )
    raise StructuredOutputError(f"LLM output failed validation: {last_error}") from last_error


def _extract_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise StructuredOutputError("LLM response does not contain a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise StructuredOutputError("LLM response contains an incomplete JSON object")
