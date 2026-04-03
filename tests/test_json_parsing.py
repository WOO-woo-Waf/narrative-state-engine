from narrative_state_engine.llm.json_parsing import JsonBlobParser


def test_json_blob_parser_extracts_fenced_json():
    parser = JsonBlobParser()
    result = parser.parse('```json\n{"accepted_updates":["a","b"]}\n```')

    assert result.ok is True
    assert result.data["accepted_updates"] == ["a", "b"]


def test_json_blob_parser_repairs_unescaped_newline_in_string():
    parser = JsonBlobParser()
    raw = '{"content":"第一行\n第二行","rationale":"ok","planned_beat":"p","style_targets":[],"continuity_notes":[]}'
    malformed = raw.replace("\\n", "\n")

    result = parser.parse(malformed)

    assert result.ok is True
    assert result.repair_applied is True
    assert "escape_control_chars_in_strings" in result.repair_notes
    assert "第一行" in result.data["content"]


def test_json_blob_parser_accepts_single_quote_python_literal():
    parser = JsonBlobParser()
    raw = "{'accepted_updates': [], 'notes': ['fallback']}"

    result = parser.parse(raw)

    assert result.ok is True
    assert result.repair_applied is True
    assert isinstance(result.data, dict)
    assert result.data["notes"] == ["fallback"]
