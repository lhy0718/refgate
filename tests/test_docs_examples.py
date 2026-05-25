from pathlib import Path

from refgate.paper_template import render_paper_agents_template


ROOT = Path(__file__).resolve().parents[1]


def test_paper_repo_example_uses_paper_audit_as_default_entrypoint():
    agents = (ROOT / "examples" / "paper-repo" / "AGENTS.md").read_text(encoding="utf-8")
    workflow = (ROOT / "examples" / "paper-repo" / ".github" / "workflows" / "refgate-paper-audit.yml").read_text(
        encoding="utf-8"
    )

    assert "refgate paper-audit" in agents
    assert "refgate paper-audit" in workflow
    assert "--next-plan-output .refgate/next_plan.json" in agents
    assert "--next-plan-output .refgate/next_plan.json" in workflow
    assert "|| true" not in workflow


def test_generated_paper_agents_template_mentions_ci_and_next_actions():
    text = render_paper_agents_template(
        tex="paper.tex",
        bib="references.bib",
        lock="refgate.lock.json",
        claims="refgate_claims.tsv",
        report="refgate_audit.md",
        command="refgate",
    )

    assert "refgate paper-audit" in text
    assert "refgate run-next --from .refgate/next_plan.json --json" in text
    assert "refgate-paper-audit" in text
    assert "bootstrap-paper" not in text


def test_live_smoke_manifest_doc_keeps_reviewed_cache_out_of_public_repo():
    text = (ROOT / "docs" / "live_smoke_reviewed_manifest.md").read_text(encoding="utf-8")

    assert "live-smoke-suite" in text
    assert "--write-manifest .refgate/cache_manifest.reviewed.json" in text
    assert "Do not commit `.refgate/cache` or reviewed cache manifests" in text
