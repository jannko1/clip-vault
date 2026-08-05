"""
Wikimedia Local Search — FTS5 full-text search against the local SQLite index.
Instant results. No API calls. Fall back to API cascade if local DB has < N results.

Usage:
  from wikimedia_local import search_wikimedia_local
  results = search_wikimedia_local("mountain sunset", per_page=20)
"""
import sqlite3
import os
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "wikimedia_index.db"
# On Vercel, the api/ dir is the source, so the DB is at api/data/
_DB_PATH_VERCEL = Path(__file__).parent / "api" / "data" / "wikimedia_index.db"

# Vercel serverless: filesystem is read-only. Open SQLite in read-only mode.
_IS_VERCEL = bool(os.environ.get("VERCEL"))

def _resolve_db_path():
    """Find the DB — try Vercel path first, then local path."""
    if _DB_PATH_VERCEL.exists():
        return _DB_PATH_VERCEL
    return DB_PATH

def _get_conn():
    """Get SQLite connection — read-only on Vercel, read-write locally."""
    db_path = _resolve_db_path()
    if _IS_VERCEL:
        db_uri = f"file:{db_path}?mode=ro"
        return sqlite3.connect(db_uri, uri=True)
    return sqlite3.connect(str(db_path))

# ── Helpers ─────────────────────────────────────────────

def _extract_visual_keywords(query: str) -> list:
    """Extract visual nouns from search query."""
    stop_words = {
        "a", "the", "in", "on", "at", "to", "for", "of", "with", "by",
        "shot", "scene", "closeup", "wide", "angle", "drone", "aerial",
        "slow", "fast", "motion", "camera", "footage", "lighting", "mood",
        "golden", "blue", "natural", "sunlight", "handheld", "studio",
        "sipping", "drinking", "walking", "standing", "sitting",
        "morning", "evening", "night", "nostalgia", "vintage", "and",
        "that", "this", "from", "have", "has", "was", "are", "were",
        "just", "like", "some", "any", "all", "when", "where", "who",
        "how", "what", "why", "then", "than", "into", "onto", "about",
        "over", "under", "above", "below", "between", "through", "around",
    }
    keywords = []
    for word in query.lower().split():
        w = word.strip(",.-+!?\"'()[]{}").rstrip("s")
        if w and len(w) > 1 and w not in stop_words:
            keywords.append(w)
    return list(dict.fromkeys(keywords))


def _format_result(row) -> dict:
    """Convert DB row to ClipVault-format result dict."""
    return {
        "id": f"wikimedia-local-{row[0]}",
        "source": "Wikimedia",
        "source_url": row[11] or "",  # page_url
        "thumbnail": row[5] or "",    # thumb_url
        "preview": row[5] or "",      # thumb_url as preview (videos need API for mp4)
        "download_url": "",           # Filled on-demand via API
        "duration": row[8] or 0,
        "width": row[6] or 0,
        "height": row[7] or 0,
        "author": "Wikimedia Commons",
        "description": row[2] or "",
        "title_raw": row[1],
        "license": row[4] or "",
        "type": "video",
        "_index_score": getattr(row, '_score', 0),
    }


# ── Search ──────────────────────────────────────────────

def search_wikimedia_local(query: str, per_page: int = 20) -> list:
    """
    Search local Wikimedia index using FTS5.
    Returns results in ClipVault-compatible format.
    Falls back to empty list if DB doesn't exist or has no results.
    """
    db_path = _resolve_db_path()
    if not db_path.exists():
        return []

    keywords = _extract_visual_keywords(query)
    if not keywords:
        return []

    conn = _get_conn()
    conn.row_factory = sqlite3.Row

    results = []
    seen_ids = set()

    # Strategy: search each keyword independently, merge by relevance score
    # This catches "mountain sunset" even if no single clip has both words

    fts_query_parts = []
    for kw in keywords[:5]:  # Max 5 keywords to keep FTS query reasonable
        # Escape FTS5 special characters and add prefix matching
        clean_kw = kw.replace('"', '').replace("'", "")
        if clean_kw:
            fts_query_parts.append(f'("{clean_kw}"*)')

    if not fts_query_parts:
        conn.close()
        return []

    fts_query = " OR ".join(fts_query_parts)

    try:
        rows = conn.execute("""
            SELECT c.*, rank
            FROM clips_fts
            JOIN clips c ON clips_fts.rowid = c.page_id
            WHERE clips_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, per_page * 3)).fetchall()  # Fetch more, we'll re-rank

        # Re-rank by keyword overlap (better than raw FTS rank for multi-word queries)
        scored = []
        for row in rows:
            title = (row["title"] or "").lower()
            desc = (row["description"] or "").lower()
            cats = (row["categories"] or "").lower()

            score = 0
            for kw in keywords:
                if kw in title:
                    score += 3
                elif kw in desc:
                    score += 2
                elif kw in cats:
                    score += 1

            # Bonus for exact phrase match
            if query.lower() in title:
                score += 5

            if score > 0:
                scored.append((score, row))

        # Sort by score descending, take top results
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, row in scored[:per_page]:
            result = _format_result(row)
            if result["id"] not in seen_ids:
                seen_ids.add(result["id"])
                result["_index_score"] = score
                results.append(result)

    except sqlite3.OperationalError as e:
        print(f"[wikimedia_local] FTS search error: {e}")
    finally:
        conn.close()

    return results


def index_has_results(query: str, min_results: int = 3) -> bool:
    """Quick check: does the local index have results for this query?"""
    results = search_wikimedia_local(query, per_page=min_results)
    return len(results) >= min_results


def index_stats() -> dict:
    """Return index statistics for status endpoint."""
    db_path = _resolve_db_path()
    vercel_db = Path(__file__).parent / "data" / "wikimedia_index.db"
    
    # Debug: report which paths we checked
    debug_info = {
        "db_path_exists": db_path.exists(),
        "db_path": str(db_path),
        "vercel_path": str(vercel_db),
        "vercel_path_exists": vercel_db.exists(),
        "is_vercel": _IS_VERCEL,
        "cwd": str(Path.cwd()),
    }
    
    if not db_path.exists():
        return {"exists": False, "total": 0, "last_updated": None, "_debug": debug_info}

    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        last_update = conn.execute(
            "SELECT value FROM index_meta WHERE key='last_full_index'"
        ).fetchone()
        conn.close()

        return {
            "exists": True,
            "total": total,
            "last_updated": last_update[0] if last_update else None,
        }
    except sqlite3.OperationalError:
        return {"exists": False, "total": 0, "last_updated": None, "error": "read-only filesystem"}


def get_download_url(page_id: int) -> str:
    """Fetch actual download URL from DB. If missing, caller should use API."""
    db_path = _resolve_db_path()
    if not db_path.exists():
        return ""

    conn = _get_conn()
    row = conn.execute(
        "SELECT thumb_url, page_url FROM clips WHERE page_id = ?", (page_id,)
    ).fetchone()
    conn.close()

    if row:
        return row[0]  # thumb_url is the best proxy; real video URL needs API
    return ""