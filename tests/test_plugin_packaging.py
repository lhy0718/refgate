import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "refgate"


def test_codex_plugin_manifest_and_marketplace_are_wired():
    manifest_path = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
    marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
    assets_path = PLUGIN_ROOT / "assets"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "refgate"
    assert manifest["skills"] == "./skills/"
    assert manifest["interface"]["displayName"] == "refgate"
    assert manifest["interface"]["category"] == "Research"
    assert "Local CLI workflow" in manifest["interface"]["capabilities"]
    assert len(manifest["interface"]["defaultPrompt"]) >= 3
    assert marketplace["plugins"][0]["name"] == manifest["name"]
    assert marketplace["plugins"][0]["source"]["path"] == "./plugins/refgate"
    assert marketplace["plugins"][0]["policy"]["installation"] == "AVAILABLE"
    assert marketplace["plugins"][0]["policy"]["authentication"] == "ON_INSTALL"
    assert (assets_path / "icon.svg").exists()
    assert (assets_path / "screenshot-cli.svg").exists()


def test_codex_plugin_skill_is_public_and_cli_first():
    skill_path = PLUGIN_ROOT / "skills" / "refgate" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")

    forbidden_terms = [
        "/" + "Users/",
        "/" + "private/",
        "/" + "tmp/",
        "Obs" + "idian",
        "reference-manager storage",
        "API " + "key",
        "to" + "ken",
        "pass" + "word",
        "sec" + "ret",
    ]
    for term in forbidden_terms:
        assert term not in text

    assert "Refgate is CLI-first" in text
    assert "Do not invent an MCP or server workflow" in text
    assert "Live network checks are opt-in only." in text
    assert "Abstracts, summaries, and metadata snippets are weak evidence only" in text
    assert "SOURCE_TITLE_MISMATCH" not in text
