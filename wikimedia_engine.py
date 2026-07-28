#!/usr/bin/env python3
"""
Wikimedia Commons Search Engine
Standalone search + metadata + cache module for royalty-free Commons media.
Integrates into ClipVault's existing source system.

Key features:
- Searches Wikimedia Commons via MediaWiki API
- Filters to royalty-free licenses only (CC0, PD, CC-BY, CC-BY-SA)
- Retrieves full metadata (duration, resolution, codec, license, thumbnail)
- Caches results for fast retrieval
- Normalizes output to ClipVault format
"""

import json
import time
import urllib.request
import urllib.parse
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timedelta

# ── Constants ──────────────────────────────────────────────────────────

USER_AGENT = "ClipVault/2.0 (https://github.com/jannko1/clip-vault; jannko1@gmail.com)"
API_BASE = "https://commons.wikimedia.org/w/api.php"
SEARCH_LIMIT = 20  # Per-page
METADATA_BATCH = 20  # Titles per batch metadata request

# Only these licenses are safe for commercial/royalty-free use
SAFE_LICENSES = {
    "public domain", "cc0", "cc-zero",
    "cc by 1.0", "cc by 2.0", "cc by 2.5", "cc by 3.0", "cc by 4.0",
    "cc-by-1.0", "cc-by-2.0", "cc-by-2.5", "cc-by-3.0", "cc-by-4.0",
    "cc by-sa 1.0", "cc by-sa 2.0", "cc by-sa 2.5", "cc by-sa 3.0", "cc by-sa 4.0",
    "cc-by-sa-1.0", "cc-by-sa-2.0", "cc-by-sa-2.5", "cc-by-sa-3.0", "cc-by-sa-4.0",
    "pd", "pd-old", "pd-us", "pd-self", "pd-user",
    "cc-pd", "copyrighted free use",
}
REJECTED_LICENSES = {
    "cc by-nc", "cc-by-nc", "cc by-nc-sa", "cc-by-nc-sa",
    "cc by-nd", "cc-by-nd", "cc by-nc-nd", "cc-by-nc-nd",
    "all rights reserved", "unknown", "none",
}

# ── Cache ───────────────────────────────────────────────────────────────

CACHE_DIR = Path(__file__).parent / "wikimedia_cache"
CACHE_DB_PATH = CACHE_DIR / "wikimedia.db"


def _get_cache_db():
    """Get or create the SQLite cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            media_type TEXT DEFAULT 'video',
            result_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(query, media_type)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_cache (
            file_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def cache_search(query: str, results: list, media_type: str = "video"):
    """Cache search results for a query."""
    try:
        conn = _get_cache_db()
        conn.execute("""
            INSERT OR REPLACE INTO search_cache (query, media_type, result_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (query.lower(), media_type, json.dumps(results), time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_cached_search(query: str, media_type: str = "video", ttl: int = 600) -> list | None:
    """Get cached search results if not expired (default 10 min TTL)."""
    try:
        conn = _get_cache_db()
        row = conn.execute(
            "SELECT result_json, created_at FROM search_cache WHERE query = ? AND media_type = ?",
            (query.lower(), media_type)
        ).fetchone()
        conn.close()
        if row and (time.time() - row[1]) < ttl:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def cache_files(files: list):
    """Cache file metadata."""
    try:
        conn = _get_cache_db()
        now = time.time()
        for f in files:
            conn.execute(
                "INSERT OR REPLACE INTO file_cache (file_id, title, metadata_json, created_at) VALUES (?, ?, ?, ?)",
                (f.get("id", ""), f.get("title", ""), json.dumps(f), now)
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── API Client ──────────────────────────────────────────────────────────

def _api_get(params: dict) -> dict:
    """Make a GET request to Wikimedia API with User-Agent header."""
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[Wikimedia API Error] {e}")
        return {}


def _api_post(params: dict) -> dict:
    """Make a POST request (for large batch queries)."""
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API_BASE, data=data, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[Wikimedia API Error] {e}")
        return {}


# ── Search ──────────────────────────────────────────────────────────────

def search_files(query: str, limit: int = 20) -> list:
    """
    Search Wikimedia Commons for files matching query.
    Returns list of {title, pageid, snippet}.
    """
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",  # File namespace only
        "gsrlimit": min(limit, 50),
        "gsrwhat": "text",  # Search file descriptions, not just titles
        "gsrinfo": "totalhits",
        "format": "json",
        "origin": "*",
    }
    data = _api_get(params)

    files = []
    pages = data.get("query", {}).get("pages", {})
    for pageid, page in pages.items():
        files.append({
            "pageid": pageid,
            "title": page.get("title", ""),
            "ns": page.get("ns", 6),
        })
    return files


# ── Metadata ────────────────────────────────────────────────────────────

def get_file_metadata(titles: list[str]) -> dict:
    """
    Get detailed metadata for a batch of file titles.
    Returns {title: {license, duration, width, height, thumb_url, download_url, author, ...}}
    """
    if not titles:
        return {}

    # Step 1: Get basic info (size, mime, mediatype) + license
    params = {
        "action": "query",
        "titles": "|".join(titles),
        "prop": "imageinfo",
        "iiprop": "size|mime|url|mediatype|extmetadata|metadata",
        "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription|Copyrighted",
        "iiurlwidth": "640",
        "format": "json",
        "origin": "*",
    }

    # Use POST for large batches (more titles = longer URL)
    if len(titles) > 10:
        data = _api_post(params)
    else:
        data = _api_get(params)

    results = {}
    pages = data.get("query", {}).get("pages", {})

    for pageid, page in pages.items():
        title = page.get("title", "")
        info = (page.get("imageinfo") or [{}])[0]

        # Parse license
        extmeta = info.get("extmetadata", {})
        license_raw = extmeta.get("LicenseShortName", {}).get("value", "")
        license_str = license_raw.lower().strip()

        # Parse duration + resolution from metadata
        duration = 0
        width = info.get("width", 0)
        height = info.get("height", 0)
        resolution_x = 0
        resolution_y = 0

        for meta in info.get("metadata", []):
            name = meta.get("name", "")
            if name == "playtime_seconds":
                try:
                    duration = float(meta.get("value", 0))
                except (ValueError, TypeError):
                    pass
            elif name == "video" and isinstance(meta.get("value"), list):
                for vitem in meta["value"]:
                    vname = vitem.get("name", "")
                    if vname == "resolution_x":
                        try:
                            resolution_x = int(vitem.get("value", 0))
                        except (ValueError, TypeError):
                            pass
                    elif vname == "resolution_y":
                        try:
                            resolution_y = int(vitem.get("value", 0))
                        except (ValueError, TypeError):
                            pass

        # Use video resolution if available
        if resolution_x and resolution_y:
            width, height = resolution_x, resolution_y

        # Author
        author = extmeta.get("Artist", {}).get("value", "")
        if not author:
            author = "Wikimedia Commons"

        # Thumbnail
        thumb_url = info.get("thumburl", "")
        if not thumb_url:
            # Fallback: use raw URL with thumb parameter
            raw_url = info.get("url", "")
            if raw_url:
                thumb_url = f"{raw_url}?width=640"

        # Download URL (raw file)
        download_url = info.get("url", "")
        if not download_url and title:
            # Fallback: construct URL from title
            encoded = title.replace("File:", "").replace(" ", "_")
            download_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(encoded)}"

        # Mediatype
        mediatype = info.get("mediatype", "").upper()

        results[title] = {
            "license": license_str,
            "license_raw": license_raw,
            "duration": duration,
            "width": width,
            "height": height,
            "thumbnail": thumb_url,
            "download_url": download_url,
            "author": author,
            "description": extmeta.get("ImageDescription", {}).get("value", "") or title,
            "mime": info.get("mime", ""),
            "mediatype": mediatype,
            "size_bytes": info.get("size", 0),
            "title": title,
        }

    return results


# ── Filter ──────────────────────────────────────────────────────────────

def is_safe_license(license_str: str) -> bool:
    """Check if a license string is royalty-free safe."""
    if not license_str:
        return False

    clean = license_str.lower().strip()

    # Direct match
    if clean in SAFE_LICENSES:
        return True

    # Partial match — catch variants
    for safe in SAFE_LICENSES:
        if safe in clean or clean in safe:
            return True

    # Explicitly reject known bad licenses
    for bad in REJECTED_LICENSES:
        if bad in clean:
            return False

    return False


# ── Normalize → ClipVault Format ────────────────────────────────────────

def normalize_result(meta: dict, is_first: bool = False) -> dict | None:
    """
    Convert Wikimedia metadata to ClipVault standard format.
    Returns None for rejected items (bad license, no download URL).
    """
    license_str = meta.get("license", "")

    # Safety check
    if not is_safe_license(license_str):
        return None

    # Must have a download URL
    if not meta.get("download_url"):
        return None

    file_id = meta.get("title", "").replace("File:", "")
    # Strip file extension from title for display
    clean_title = Path(file_id).stem if "." in file_id else file_id
    clean_title = clean_title.replace("_", " ")

    return {
        "id": f"wikimedia-{file_id[:50]}",
        "source": "Wikimedia",
        "source_url": f"https://commons.wikimedia.org/wiki/{meta['title'].replace(' ', '_')}",
        "thumbnail": meta.get("thumbnail", ""),
        "preview": meta.get("download_url", ""),  # Wikimedia: preview = download (no separate)
        "download_url": meta.get("download_url", ""),
        "duration": meta.get("duration", 0),
        "width": meta.get("width", 0),
        "height": meta.get("height", 0),
        "author": meta.get("author", "Wikimedia Commons"),
        "description": meta.get("description", ""),
        "title_raw": clean_title,
        "tags": "",
        "license": license_str,
        "type": "video" if meta.get("mediatype") == "VIDEO" else "image",
    }


# ── Main Search Entry Point ─────────────────────────────────────────────

def search_wikimedia(query: str, media_type: str = "video", limit: int = 20) -> list:
    """
    Main search function — drop-in for ClipVault.
    1. Check cache
    2. Search API → get file titles
    3. Batch metadata → get license/duration/resolution
    4. Filter by safe license
    5. Normalize to ClipVault format
    6. Cache results
    """
    # Check cache first
    cached = get_cached_search(query, media_type)
    if cached is not None:
        return cached

    # Search
    files = search_files(query, limit=limit * 2)  # Over-fetch to account for filtering

    if not files:
        cache_search(query, [], media_type)
        return []

    # Batch metadata
    titles = [f["title"] for f in files]
    metadata = get_file_metadata(titles)

    # Filter + normalize
    results = []
    for f in files:
        meta = metadata.get(f["title"])
        if not meta:
            continue

        normalized = normalize_result(meta)
        if normalized is None:
            continue

        # Type filter
        if media_type == "video" and normalized["type"] != "video":
            continue
        if media_type == "image" and normalized["type"] != "image":
            continue

        results.append(normalized)

        if len(results) >= limit:
            break

    # Cache
    cache_search(query, results, media_type)
    cache_files(results)

    return results


# ── Pre-indexer (run once to warm cache) ────────────────────────────────

POPULAR_QUERIES = [
    "nature landscape", "city timelapse", "ocean waves", "sunset sky",
    "mountain aerial", "forest trees", "river water", "clouds sky",
    "animals wildlife", "birds flying", "people walking", "traffic cars",
    "business office", "technology computer", "food cooking", "abstract background",
    "flowers garden", "space stars", "underwater fish", "drone aerial",
]


def pre_index(queries: list = None):
    """Pre-populate the cache with common search queries."""
    queries = queries or POPULAR_QUERIES
    print(f"📡 Pre-indexing {len(queries)} Wikimedia queries...")
    for i, q in enumerate(queries):
        results = search_wikimedia(q, limit=10)
        print(f"   {i+1}/{len(queries)}: '{q}' → {len(results)} results")
        time.sleep(0.3)  # Be respectful to API
    print(f"✅ Cache warmed with {len(queries)} queries")


# ── CLI ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--pre-index":
        pre_index()
    elif len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"🔍 Searching Wikimedia: '{query}'")
        results = search_wikimedia(query)

        if results:
            print(f"\n✅ {len(results)} royalty-free results:\n")
            for i, r in enumerate(results[:10], 1):
                dur = f"{r['duration']:.0f}s" if r['duration'] else "N/A"
                print(f"  {i:2}. {r['title_raw'][:50]:50s} | {dur:>6s} | "
                      f"{r['width']}×{r['height']} | {r['license']}")
        else:
            print("   No results found.")
    else:
        print("Usage: python wikimedia_engine.py <query>")
        print("       python wikimedia_engine.py --pre-index")
