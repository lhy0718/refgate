import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "refgate"
COMMAND_DIR = PLUGIN_ROOT / "commands"

COMMAND_NAMES = {
    "refgate-paper-audit",
    "refgate-reference-check",
    "refgate-claim-review",
    "refgate-run-next",
    "refgate-final-audit",
    "refgate-publish-check",
}


def test_claude_code_plugin_manifest_and_marketplace_are_wired():
    manifest_path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "refgate"
    assert manifest["version"]
    assert manifest["description"]
    assert marketplace["plugins"][0]["name"] == manifest["name"]
    assert marketplace["plugins"][0]["source"] == "./plugins/refgate"


def test_claude_code_command_pack_is_present_and_portable():
    actual = {path.stem for path in COMMAND_DIR.glob("*.md")}

    assert COMMAND_NAMES <= actual

    forbidden_terms = [
        "/" + "Users/",
        "Obs" + "idian",
        "Zo" + "tero " + "storage",
        "API " + "key",
        "to" + "ken",
        "pass" + "word",
        "sec" + "ret",
    ]
    scanned = list(COMMAND_DIR.glob("*.md")) + [
        PLUGIN_ROOT / "skills" / "refgate" / "SKILL.md",
        ROOT / "CLAUDE.md",
        ROOT / "docs" / "claude_code.md",
    ]
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text
        assert "refgate" in text.lower()


def test_claude_code_commands_declare_frontmatter():
    for path in COMMAND_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        header = text.split("---\n", 2)[1]
        assert "description:" in header
        assert "argument-hint:" in header


def test_claude_code_hook_is_plugin_scoped_and_advisory():
    hooks_path = PLUGIN_ROOT / "hooks" / "hooks.json"
    hook_path = PLUGIN_ROOT / "hooks" / "refgate-post-edit-reminder.sh"

    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    entry = hooks["hooks"]["PostToolUse"][0]["hooks"][0]

    # Plugin hooks run from a version-pinned cache directory, so the command
    # must resolve through CLAUDE_PLUGIN_ROOT rather than the project path.
    assert "${CLAUDE_PLUGIN_ROOT}" in entry["command"]
    assert entry["command"].endswith("/hooks/refgate-post-edit-reminder.sh")

    assert hook_path.exists()
    hook_text = hook_path.read_text(encoding="utf-8")
    assert "refgate reminder" in hook_text.lower()
    # The reminder must name the namespaced plugin commands, not bare ones.
    assert "/refgate:refgate-paper-audit" in hook_text
    assert "/refgate:refgate-final-audit" in hook_text


def test_claude_code_surface_is_not_duplicated_at_project_level():
    """The plugin is the single source for the Claude Code surface.

    A project-level ``.claude/commands/refgate/`` copy registers the same six
    commands under the same ``refgate:`` namespace, and a project-level hook
    copy fires the reminder twice. Refgate is a deterministic gate, so the
    duplicate paths must be absent outright rather than merely untracked.
    """
    superseded = [
        ROOT / ".claude" / "commands" / "refgate",
        ROOT / ".claude" / "hooks" / "refgate-post-edit-reminder.sh",
        ROOT / ".claude" / "settings.refgate.example.json",
    ]
    present = [str(path.relative_to(ROOT)) for path in superseded if path.exists()]

    assert not present, (
        "Superseded project-level Claude Code files found: "
        + ", ".join(present)
        + ". The refgate plugin under plugins/refgate is the single source for "
        "commands, the skill, and the post-edit reminder hook; remove these copies."
    )
