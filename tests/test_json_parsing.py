from narrative_state_engine.llm.json_parsing import JsonBlobParser


def test_json_blob_parser_extracts_fenced_json():
    parser = JsonBlobParser()
    result = parser.parse('```json\n{"accepted_updates":["a","b"]}\n```')

    assert result.ok is True
    assert result.data["accepted_updates"] == ["a", "b"]
