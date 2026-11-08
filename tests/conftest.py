import pytest


@pytest.fixture(autouse=True)
def _isolate_working_directory(tmp_path, monkeypatch):
    """Run every test from its own tmp_path.

    Several CLI defaults are relative to the working directory
    (paper-audit --report refgate_audit.md and --resolver-output
    refgate_queries.json, --cache-root .refgate/cache). A test that leaves
    one of them out would otherwise write into the repository root.
    """
    monkeypatch.chdir(tmp_path)
