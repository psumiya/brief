"""
RAG layer: embed past brief content into sqlite-vec, retrieve historical context at synthesis time.

Usage:
  python rag.py --backfill          # embed all briefs in output/brief-*.json
  python rag.py --query "some text" # test retrieval
"""

import json
import os
import sqlite3
import struct
from pathlib import Path
from typing import Optional

RAG_DB = Path("output/rag.db")
OUTPUT_DIR = Path("output")
EMBEDDING_MODEL = "gemini-embedding-001"
EMBED_DIM = 3072
TOP_K = 5


# ── DB setup ───────────────────────────────────────────────────────────────────

def _load_vec_extension(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (ImportError, AttributeError) as e:
        raise RuntimeError(f"sqlite-vec not available: {e}") from e


def init_db(db_path: Path = RAG_DB) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    _load_vec_extension(conn)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            brief_date TEXT NOT NULL,
            chunk_type TEXT NOT NULL,
            text      TEXT NOT NULL,
            metadata  TEXT NOT NULL DEFAULT '{{}}'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings USING vec0(
            embedding FLOAT[{EMBED_DIM}]
        );
    """)
    conn.commit()
    return conn


# ── Embedding ──────────────────────────────────────────────────────────────────

def _embedding_client(client=None):
    if client is not None:
        return client
    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return genai.Client(api_key=api_key)


def embed_text(text: str, client=None) -> list[float]:
    c = _embedding_client(client)
    result = c.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    return result.embeddings[0].values


def _serialize(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


# ── Indexing ───────────────────────────────────────────────────────────────────

def _brief_chunks(brief: dict, date: str) -> list[dict]:
    chunks = []
    for dt in brief.get("deep_takes", []):
        body = " ".join(dt.get("body", []))
        if body.strip():
            chunks.append({
                "chunk_type": "deep_take",
                "text": f"{dt.get('headline', '')}. {body}",
                "metadata": {"headline": dt.get("headline", ""), "kicker": dt.get("kicker", "")},
            })
    for b in brief.get("bullets", []):
        if b.get("text"):
            chunks.append({
                "chunk_type": "bullet",
                "text": b["text"],
                "metadata": {"source": b.get("source", ""), "theme": b.get("theme", "")},
            })
    for t in brief.get("narrative_threads", []):
        if t.get("summary"):
            chunks.append({
                "chunk_type": "thread",
                "text": f"{t.get('title', '')}. {t['summary']}",
                "metadata": {"id": t.get("id", ""), "status": t.get("status", "")},
            })
    return chunks


def index_brief(brief: dict, date: str, db_path: Path = RAG_DB, client=None) -> int:
    conn = init_db(db_path)
    already = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE brief_date = ?", (date,)
    ).fetchone()[0]
    if already > 0:
        conn.close()
        return 0

    chunks = _brief_chunks(brief, date)
    inserted = 0
    for chunk in chunks:
        embedding = embed_text(chunk["text"], client=client)
        cur = conn.execute(
            "INSERT INTO chunks (brief_date, chunk_type, text, metadata) VALUES (?, ?, ?, ?)",
            (date, chunk["chunk_type"], chunk["text"], json.dumps(chunk["metadata"])),
        )
        row_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chunk_embeddings (rowid, embedding) VALUES (?, ?)",
            (row_id, _serialize(embedding)),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


# ── Retrieval ──────────────────────────────────────────────────────────────────

def retrieve_context(query_texts: list[str], db_path: Path = RAG_DB, top_k: int = TOP_K, client=None) -> list[dict]:
    if not db_path.exists():
        return []

    conn = init_db(db_path)
    results = []
    seen_texts = set()

    for query in query_texts:
        embedding = embed_text(query, client=client)
        serialized = _serialize(embedding)
        rows = conn.execute(
            """
            SELECT c.brief_date, c.chunk_type, c.text, c.metadata, ce.distance
            FROM chunk_embeddings ce
            JOIN chunks c ON c.id = ce.rowid
            WHERE ce.embedding MATCH ?
              AND k = ?
            ORDER BY ce.distance
            """,
            (serialized, top_k),
        ).fetchall()
        for row in rows:
            text = row[2]
            if text not in seen_texts:
                seen_texts.add(text)
                results.append({
                    "brief_date": row[0],
                    "chunk_type": row[1],
                    "text": text,
                    "metadata": json.loads(row[3]),
                    "distance": row[4],
                })

    conn.close()
    results.sort(key=lambda r: r["distance"])
    return results[:top_k]


def build_rag_context_block(query_texts: list[str], db_path: Path = RAG_DB, client=None) -> str:
    if not query_texts:
        return ""
    chunks = retrieve_context(query_texts, db_path=db_path, client=client)
    if not chunks:
        return ""
    lines = ["RELATED HISTORICAL CONTEXT (from past briefs — use to identify recurring stories):"]
    for c in chunks:
        lines.append(f"  [{c['brief_date']} / {c['chunk_type']}] {c['text'][:300]}")
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--query", type=str)
    args = parser.parse_args()

    if args.backfill:
        brief_files = sorted(OUTPUT_DIR.glob("brief-*.json"))
        print(f"Backfilling {len(brief_files)} briefs into {RAG_DB}…")
        for p in brief_files:
            date = p.stem.replace("brief-", "")
            brief = json.loads(p.read_text())
            n = index_brief(brief, date)
            print(f"  {date}: {n} chunks indexed")
        print("Done.")

    elif args.query:
        results = retrieve_context([args.query])
        for r in results:
            print(f"[{r['brief_date']} / {r['chunk_type']}] dist={r['distance']:.4f}")
            print(f"  {r['text'][:200]}")
            print()

    else:
        parser.print_help()
