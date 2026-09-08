import json

import pytest

from app.model_config.connection import ProbeError
from app.model_config.output import check_output
from app.project.schema import validate_map
from app.training.evaluation_schema import evaluation_inputs, validate_grading
from app.training.generation import extract_content
from app.training.schema import validate_candidate
from tests.test_evaluation_schema import example

KEY = "controlled-current-key"


def escaped(value):
    return json.dumps(value).replace(KEY, "".join(f"\\u{ord(c):04x}" for c in KEY))


@pytest.mark.parametrize("transport", ["application/json", "text/event-stream"])
def test_decoded_secret_rejected_in_json_and_sse_with_usage(transport):
    raw = escaped({"explanation": KEY})
    if transport == "application/json":
        body = json.dumps({"choices": [{"message": {"content": raw}}]}).encode()
    else:
        body = (
            "data: "
            + json.dumps({"choices": [{"index": 0, "delta": {"content": raw}}]})
            + "\n\ndata: [DONE]\n\n"
        ).encode()
    with pytest.raises(ProbeError) as error:
        extract_content(body, transport, {"total_tokens": 20}, KEY)
    assert (
        error.value.code == "invalid_response"
        and error.value.counts["total_tokens"] == 20
    )


def test_all_candidate_boundaries_reject_decoded_key():
    case, sources, original, result = example()
    result["items"][0]["explanation"] = KEY
    with pytest.raises(ValueError, match="unsafe model output"):
        validate_grading(
            escaped(result), case, sources, evaluation_inputs([original]), KEY
        )
    data = case.model_dump()
    data["title"] = KEY
    with pytest.raises(ValueError, match="unsafe model output"):
        validate_candidate(escaped(data), case.target, sources, KEY)
    with pytest.raises(ValueError, match="unsafe model output"):
        validate_map(escaped({"findings": [], "missing": [KEY]}), [], KEY)


def test_nested_decoded_secret_patterns_and_nonsecret_output():
    secret = "sk-" + "A" * 26
    raw = json.dumps({"nested": [secret]}).replace("sk-", "\\u0073\\u006b\\u002d")
    with pytest.raises(ValueError, match="unsafe model output"):
        check_output(raw, "different-current-key")
    check_output('{"text": "普通非秘密文本"}', KEY)
    check_output(
        "not-json", KEY
    )  # Existing candidate parser still decides malformed retries.
