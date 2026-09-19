from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    """The archive itself. Tests assert against it, so they skip without it."""
    from acme_agent.core import CONFIG
    if not CONFIG.corpus_dir.exists():
        pytest.skip(f"corpus not available at {CONFIG.corpus_dir}; "
                    f"set ACME_CORPUS_DIR in .env")
    return CONFIG.corpus_dir


@pytest.fixture(scope="session")
def registry(corpus_dir):
    from acme_agent.core import build_registry
    return build_registry("".join(p.read_text(encoding="utf-8")
                                  for p in corpus_dir.glob("*/*.txt")))


@pytest.fixture
def store(corpus_dir, tmp_path):
    """A freshly built index in a temp dir, so tests never touch real state."""
    from acme_agent.core import Store
    from acme_agent.ingest import build_index
    build_index(corpus_dir, tmp_path / "index.json")
    return Store.load(tmp_path / "index.json")
