from __future__ import annotations
import json
from pathlib import Path
import jsonschema

def test_tool_response_schema_examples():
    schema_path = Path("mcp_server/schemas/tool_responses.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    examples = json.loads(Path("tests/contract_examples.json").read_text(encoding="utf-8"))
    for ex in examples:
        jsonschema.validate(ex, schema)
