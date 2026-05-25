from pathlib import Path
import json

from refgate.audit import audit_bibliography
from refgate.bibtex import parse_bibtex_file
from refgate.models import Lockfile


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_bibtex_file_extracts_entry():
    bib_entries = parse_bibtex_file((FIXTURES / "sample.bib").read_text(encoding="utf-8"))

    assert "debenedetti2024agentdojo" in bib_entries
    assert bib_entries["debenedetti2024agentdojo"]["year"] == "2024"


def test_audit_bibliography_passes_verified_official_export():
    bib_text = (FIXTURES / "sample.bib").read_text(encoding="utf-8")
    lockfile = Lockfile.from_dict(json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8")))

    issues = audit_bibliography(bib_text, lockfile, submission=True)

    assert not [issue for issue in issues if issue.severity == "blocking"]
