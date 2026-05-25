"""Source adapter interfaces and built-in adapters."""

from .acl import AclAdapter
from .arxiv import ArxivAdapter
from .crossref import CrossrefAdapter
from .iclr import IclrAdapter
from .neurips import NeuripsAdapter
from .openalex import OpenAlexAdapter
from .semantic_scholar import SemanticScholarAdapter

__all__ = [
    "AclAdapter",
    "ArxivAdapter",
    "CrossrefAdapter",
    "IclrAdapter",
    "NeuripsAdapter",
    "OpenAlexAdapter",
    "SemanticScholarAdapter",
]
