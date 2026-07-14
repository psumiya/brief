import json
import struct
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


EMBED_DIM = 3072


def _mock_client(vector=None):
    if vector is None:
        vector = [0.1] * EMBED_DIM
    client = MagicMock()

    def _embed(model, contents):
        items = contents if isinstance(contents, list) else [contents]
        embs = []
        for _ in items:
            e = MagicMock()
            e.values = vector
            embs.append(e)
        return MagicMock(embeddings=embs)

    client.models.embed_content.side_effect = _embed
    return client


def _minimal_brief(date="2026-05-17"):
    return {
        "date": date,
        "deep_takes": [{"headline": "Test", "deck": "Deck", "kicker": "Lead",
                         "body": ["Para one.", "Para two."], "sources": [], "themes": [], "stack_layer": "Applications"}],
        "bullets": [{"text": "Bullet text here.", "source": "Src", "theme": "Agents & Applications",
                     "stack_layer": "Applications", "url": "https://example.com"}],
        "narrative_threads": [{"id": "t1", "title": "Thread 1", "status": "active",
                                "first_seen": date, "last_active": date, "day_count": 1,
                                "summary": "Some ongoing story about AI."}],
    }


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_rag.db"


def test_init_db_creates_tables(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import init_db
    conn = init_db(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "chunks" in tables
    conn.close()


def test_index_brief_inserts_chunks(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import index_brief
    client = _mock_client()
    n = index_brief(_minimal_brief(), "2026-05-17", db_path=db_path, client=client)
    assert n == 3  # 1 deep_take + 1 bullet + 1 thread


def test_index_brief_batches_embeddings(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import index_brief
    client = _mock_client()
    index_brief(_minimal_brief(), "2026-05-17", db_path=db_path, client=client)
    # 3 chunks embedded in a single batched API call, not one call per chunk
    assert client.models.embed_content.call_count == 1


def test_index_brief_idempotent(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import index_brief, init_db
    client = _mock_client()
    n1 = index_brief(_minimal_brief(), "2026-05-17", db_path=db_path, client=client)
    n2 = index_brief(_minimal_brief(), "2026-05-17", db_path=db_path, client=client)
    assert n2 == 0  # already indexed, skip


def test_retrieve_context_empty_db_returns_empty(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import retrieve_context
    assert retrieve_context(["query"], db_path=db_path) == []


def test_retrieve_context_returns_results(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import index_brief, retrieve_context
    client = _mock_client()
    index_brief(_minimal_brief(), "2026-05-17", db_path=db_path, client=client)
    results = retrieve_context(["AI agents"], db_path=db_path, client=client)
    assert len(results) > 0
    assert "text" in results[0]
    assert "brief_date" in results[0]


def test_build_rag_context_block_empty_db(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import build_rag_context_block
    result = build_rag_context_block(["query"], db_path=db_path)
    assert result == ""


def test_build_rag_context_block_no_queries(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import build_rag_context_block
    result = build_rag_context_block([], db_path=db_path)
    assert result == ""


def test_build_rag_context_block_with_content(db_path):
    pytest.importorskip("sqlite_vec")
    from rag import index_brief, build_rag_context_block
    client = _mock_client()
    index_brief(_minimal_brief(), "2026-05-17", db_path=db_path, client=client)
    result = build_rag_context_block(["agents"], db_path=db_path, client=client)
    assert "ALREADY COVERED IN PAST BRIEFS" in result
    assert "2026-05-17" in result
