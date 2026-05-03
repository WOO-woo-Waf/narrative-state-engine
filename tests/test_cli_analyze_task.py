from typer.testing import CliRunner

from narrative_state_engine.cli import app


def test_analyze_task_rule_mode_writes_analysis_json(tmp_path):
    source = tmp_path / "story.txt"
    output = tmp_path / "analysis.json"
    source.write_text("第一章\n雨夜里，他推开门。她低声问：“听见了吗？”", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "analyze-task",
            "--story-id",
            "story-cli-analysis",
            "--file",
            str(source),
            "--rule",
            "--no-persist",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    assert "story-cli-analysis" in output.read_text(encoding="utf-8")
