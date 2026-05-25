import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ROOT = ROOT / ".claude"


def test_claude_code_command_pack_is_present_and_portable():
    expected = {
        "refgate-paper-audit.md",
        "refgate-reference-check.md",
        "refgate-claim-review.md",
        "refgate-run-next.md",
        "refgate-final-audit.md",
        "refgate-publish-check.md",
    }
    command_dir = CLAUDE_ROOT / "commands" / "refgate"
    actual = {path.name for path in command_dir.glob("*.md")}

    assert expected <= actual

    forbidden_terms = [
        "/" + "Users/",
        "Obs" + "idian",
        "Zo" + "tero " + "storage",
        "API " + "key",
        "to" + "ken",
        "pass" + "word",
        "sec" + "ret",
    ]
    for path in list(command_dir.glob("*.md")) + [ROOT / "CLAUDE.md", ROOT / "docs" / "claude_code.md"]:
        text = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text
        assert "refgate" in text.lower()


def test_claude_code_hook_example_is_valid_json_and_opt_in():
    settings_path = CLAUDE_ROOT / "settings.refgate.example.json"
    hook_path = CLAUDE_ROOT / "hooks" / "refgate-post-edit-reminder.sh"

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hook_command = settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"]

    assert settings_path.name.endswith(".example.json")
    assert ".claude/hooks/refgate-post-edit-reminder.sh" in hook_command
    assert hook_path.exists()
    assert "refgate reminder" in hook_path.read_text(encoding="utf-8").lower()
