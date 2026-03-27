from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = pytest.mark.unit


def test_tool_response_schema_examples():
    # Validates: all contract examples conform to tool_responses JSON schema
    schema_path = Path("mcp_server/schemas/tool_responses.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    examples = json.loads(Path("tests/contract_examples.json").read_text(encoding="utf-8"))
    assert len(examples) > 0, "Contract examples file should not be empty"
    for ex in examples:
        jsonschema.validate(ex, schema)
