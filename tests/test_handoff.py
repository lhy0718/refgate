import json
from pathlib import Path

from refgate.handoff import build_handoff
from refgate.models import Lockfile


FIXTURES = Path(__file__).parent / "fixtures"


def test_csl_handoff_maps_common_bibtex_fields():
    lockfile = Lockfile.from_dict(json.loads((FIXTURES / "refgate.lock.json").read_text(encoding="utf-8")))
    bib_text = """
@inproceedings{debenedetti2024agentdojo,
  title = {AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents},
  author = {Debenedetti, Edoardo and Zhang, Jie},
  booktitle = {Advances in Neural Information Processing Systems},
  year = {2024},
  month = {dec},
  pages = {1--12},
  publisher = {Curran Associates, Inc.},
  address = {Vancouver, Canada},
  doi = {10.52202/079017-2636},
  url = {https://proceedings.neurips.cc/paper_files/paper/2024/hash/example-Abstract-Conference.html},
  abstract = {A fixture abstract.},
  keywords = {agents, security}
}
"""

    artifact = build_handoff(lockfile, bib_text, export_format="csl-json")

    item = artifact[0]
    assert item["issued"] == {"date-parts": [[2024, 12]]}
    assert item["page"] == "1--12"
    assert item["publisher"] == "Curran Associates, Inc."
    assert item["publisher-place"] == "Vancouver, Canada"
    assert item["DOI"] == "10.52202/079017-2636"
    assert item["abstract"] == "A fixture abstract."
    assert item["keyword"] == "agents, security"
    assert item["_refgate"]["bibtex_source_kind"] == "official_export"
