import os

import pytest

from refgate.adapters.arxiv import ArxivAdapter
from refgate.models import PaperQuery


pytestmark = pytest.mark.skipif(
    os.environ.get("REFGATE_LIVE_ARXIV") != "1",
    reason="Live arXiv checks are opt-in. Set REFGATE_LIVE_ARXIV=1 to run.",
)


def test_live_arxiv_exact_id_lookup_smoke():
    adapter = ArxivAdapter()
    query = PaperQuery(
        query_id="attention-is-all-you-need",
        title="Attention Is All You Need",
        authors=["Vaswani"],
        year=2017,
        arxiv_id="1706.03762",
    )

    candidates = adapter.discover(query)

    assert candidates
    assert candidates[0].arxiv_id == "1706.03762"
    assert candidates[0].raw["accessed_at"]
