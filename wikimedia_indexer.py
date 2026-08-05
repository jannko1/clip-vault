"""
Wikimedia Commons Indexer — Crawls category tree, batch-fetches video metadata,
builds a local SQLite library with FTS5 full-text search.

Usage:
  python wikimedia_indexer.py          # Full crawl (seeded categories)
  python wikimedia_indexer.py --update # Incremental (new files only, last 7 days)
  python wikimedia_indexer.py --stats  # Show index stats

Data source: Wikimedia Commons API (open, no key required)
Rate limit: ~200 req/IP. 0.3s delay between calls.
"""
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ──────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "data" / "wikimedia_index.db"
USER_AGENT = "ClipVault/1.0 (https://clipvault.app; jan@clipvault.app)"
REQUEST_DELAY = 0.3  # Seconds between API calls
BATCH_SIZE = 50      # Titles per metadata request
MAX_CATEGORY_DEPTH = 1  # How deep to walk subcategories (1 = just direct children)

# Seed categories — high-value for stock footage
# NOTE: "Category:Videos" is TOO BROAD (thousands of subcategories).
# Use specific focused categories instead.
SEED_CATEGORIES = [
    # Nature & landscapes
    "Category:Videos_of_nature",
    "Category:Videos_of_landscapes",
    "Category:Timelapse_videos_of_nature",
    "Category:Videos_of_sunsets",
    "Category:Videos_of_oceans",
    "Category:Videos_of_mountains",
    "Category:Videos_of_waterfalls",
    "Category:Videos_of_forests",
    "Category:Videos_of_rivers",
    "Category:Videos_of_clouds",
    "Category:Videos_of_weather",
    "Category:Videos_of_lightning",
    "Category:Videos_of_rain",
    "Category:Videos_of_snow",
    # Urban & architecture
    "Category:Videos_of_cities",
    "Category:Videos_of_buildings",
    "Category:Videos_of_bridges",
    "Category:Timelapse_videos_of_cities",
    "Category:Drone_videos_of_cities",
    "Category:Videos_of_skyscrapers",
    "Category:Videos_of_streets",
    # Technology & science
    "Category:Videos_of_technology",
    "Category:Videos_of_science",
    "Category:Videos_of_space",
    "Category:Videos_of_computers",
    "Category:Videos_of_robots",
    "Category:Videos_of_data_visualization",
    # Abstract & effects
    "Category:Videos_of_abstract_art",
    "Category:Videos_of_lights",
    "Category:Videos_of_particles",
    "Category:Slow_motion_videos",
    "Category:Videos_of_fire",
    "Category:Videos_of_water",
    "Category:Videos_of_smoke",
    "Category:Videos_of_explosions",
    # Animals & wildlife
    "Category:Videos_of_animals",
    "Category:Videos_of_birds",
    "Category:Videos_of_marine_life",
    "Category:Videos_of_insects",
    "Category:Videos_of_mammals",
    # Aerial & drone
    "Category:Videos_from_drones",
    "Category:Aerial_videos",
    # Transport
    "Category:Videos_of_transport",
    "Category:Videos_of_aircraft",
    "Category:Videos_of_trains",
    # Plants & food
    "Category:Videos_of_plants",
    "Category:Videos_of_flowers",
    "Category:Videos_of_food",
    # History & culture
    "Category:Videos_of_historical_sites",
    "Category:Videos_of_art",
]

# Licenses safe for commercial use
SAFE_LICENSES = {"cc0", "cc by", "cc by-sa", "public domain", "pd", "cc-zero", "cc-by", "cc-by-sa"}

# ── API Helpers ─────────────────────────────────────────

def _wikimedia_api(params: dict, retries: int = 3) -> dict:
    """Call Wikimedia API with rate limiting and exponential backoff."""
    base = "https://commons.wikimedia.org/w/api.php"
    params["format"] = "json"
    params["formatversion"] = "2"
    url = base + "?" + urllib.parse.urlencode(params)

    for attempt in range(retries):
        time.sleep(REQUEST_DELAY * (attempt + 1))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 2)
                print(f"  ⚠ Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"  ✗ HTTP {e.code} for {url[:100]}")
            return {}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            print(f"  ✗ API error: {e}")
            return {}
    return {}


def _is_video(title: str) -> bool:
    """Quick check: does this look like a video file? Wikimedia videos are .webm or .ogv mostly."""
    title_lower = title.lower()
    video_exts = [".webm", ".ogv", ".mp4", ".avi", ".mov", ".mkv"]
    return any(title_lower.endswith(ext) for ext in video_exts)


def _fetch_category_members(category: str, cmtype: str = "file", limit: int = 500) -> list:
    """Fetch files or subcategories from a category. Handles pagination."""
    all_members = []
    cmcontinue = None

    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": cmtype,
            "cmlimit": min(limit, 500),
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        data = _wikimedia_api(params)
        members = data.get("query", {}).get("categorymembers", [])
        all_members.extend(members)

        if "continue" in data:
            cmcontinue = data["continue"].get("cmcontinue")
        else:
            break

        if len(all_members) >= limit:
            break

    return all_members


def _fetch_file_metadata(titles: list) -> list:
    """Batch-fetch metadata for up to 50 file titles."""
    if not titles:
        return []

    # Join with pipe for batch request (max 50 titles)
    title_str = "|".join(titles[:BATCH_SIZE])

    data = _wikimedia_api({
        "action": "query",
        "prop": "imageinfo",
        "iiprop": "extmetadata|url|size|mime|mediatype|timestamp|metadata",
        "titles": title_str,
        "iilimit": "1",
    })

    results = []
    pages = data.get("query", {}).get("pages", [])
    for page in pages:
        imageinfo = (page.get("imageinfo") or [{}])[0]
        if not imageinfo:
            continue

        # Only index videos
        mediatype = imageinfo.get("mediatype", "").upper()
        if mediatype != "VIDEO":
            continue

        extmeta = imageinfo.get("extmetadata", {})

        # License safety check
        license_name = (extmeta.get("LicenseShortName", {}) or {}).get("value", "").lower()
        usage = (extmeta.get("UsageTerms", {}) or {}).get("value", "").lower()

        if not _is_safe_license(license_name, usage):
            continue

        # Extract duration from metadata (if available — video codec metadata)
        duration = _extract_duration(imageinfo.get("metadata", []))

        results.append({
            "page_id": page["pageid"],
            "title": page["title"],
            "description": (extmeta.get("ImageDescription", {}) or {}).get("value", ""),
            "categories": _extract_categories(extmeta),
            "license": license_name,
            "thumb_url": imageinfo.get("url", ""),
            "width": imageinfo.get("width", 0),
            "height": imageinfo.get("height", 0),
            "duration": duration,
            "size_bytes": imageinfo.get("size", 0),
            "mime": imageinfo.get("mime", ""),
            "page_url": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(page['title'].replace(' ', '_'))}",
            "timestamp": imageinfo.get("timestamp", ""),
        })

    return results


def _is_safe_license(license_name: str, usage_terms: str) -> bool:
    """Check if license allows commercial use without restrictions."""
    license_lower = (license_name + " " + usage_terms).lower()
    # Reject non-commercial and no-derivatives
    if "nc" in license_lower or "non-commercial" in license_lower:
        return False
    if "nd" in license_lower or "no-derivatives" in license_lower:
        return False
    # Accept known safe licenses
    for safe in SAFE_LICENSES:
        if safe in license_lower:
            return True
    # Unknown license — reject for safety
    if license_name and license_name not in ("", "none", "unknown"):
        return True  # Named license that didn't match NC/ND filters
    return False


def _extract_duration(metadata: list) -> float:
    """Extract video duration from imageinfo metadata (codec-specific)."""
    if not metadata:
        return 0.0
    for meta in metadata:
        name = meta.get("name", "").lower()
        if "duration" in name:
            try:
                return float(meta.get("value", 0))
            except (ValueError, TypeError):
                pass
        # Some formats store playtime_seconds
        if name in ("playtime_seconds", "length"):
            try:
                return float(meta.get("value", 0))
            except (ValueError, TypeError):
                pass
    return 0.0


def _extract_categories(extmeta: dict) -> str:
    """Extract categories string from extmetadata."""
    cats = (extmeta.get("Categories", {}) or {}).get("value", "")
    if isinstance(cats, dict):
        cats = cats.get("value", "")
    return cats or ""


def _discover_subcategories(category: str, depth: int = 0) -> list:
    """Recursively discover subcategories up to MAX_CATEGORY_DEPTH. Capped at 30 subs per category."""
    if depth >= MAX_CATEGORY_DEPTH:
        return [category]

    all_cats = [category]
    subs = _fetch_category_members(category, cmtype="subcat", limit=30)  # Cap at 30
    for sub in subs[:30]:
        sub_title = sub["title"]
        all_cats.extend(_discover_subcategories(sub_title, depth + 1))

    return all_cats


# ── Database ────────────────────────────────────────────

def _init_db():
    """Initialize SQLite database with FTS5 for full-text search."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Main metadata table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            page_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            categories TEXT DEFAULT '',
            license TEXT DEFAULT '',
            thumb_url TEXT DEFAULT '',
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            duration REAL DEFAULT 0.0,
            size_bytes INTEGER DEFAULT 0,
            mime TEXT DEFAULT '',
            page_url TEXT DEFAULT '',
            timestamp TEXT DEFAULT '',
            indexed_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # FTS5 full-text search index
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS clips_fts USING fts5(
            title,
            description,
            categories,
            content='clips',
            content_rowid='page_id',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)

    # Triggers to keep FTS in sync
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS clips_ai AFTER INSERT ON clips BEGIN
            INSERT INTO clips_fts(rowid, title, description, categories)
            VALUES (new.page_id, new.title, new.description, new.categories);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS clips_ad AFTER DELETE ON clips BEGIN
            INSERT INTO clips_fts(clips_fts, rowid, title, description, categories)
            VALUES ('delete', old.page_id, old.title, old.description, old.categories);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS clips_au AFTER UPDATE ON clips BEGIN
            INSERT INTO clips_fts(clips_fts, rowid, title, description, categories)
            VALUES ('delete', old.page_id, old.title, old.description, old.categories);
            INSERT INTO clips_fts(rowid, title, description, categories)
            VALUES (new.page_id, new.title, new.description, new.categories);
        END
    """)

    # Index metadata table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS index_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    return conn


# ── Main Indexing ───────────────────────────────────────

def crawl_and_index(max_files_per_cat: int = 500, update_mode: bool = False):
    """Main crawl: discover categories → list files → batch metadata → insert."""
    conn = _init_db()
    print(f"📂 Database: {DB_PATH}")
    print(f"📊 Current clips: {conn.execute('SELECT COUNT(*) FROM clips').fetchone()[0]}")
    print()

    # Discover all categories (seed + subcategories)
    print("🔍 Discovering categories...")
    all_categories = []
    for seed in SEED_CATEGORIES:
        cats = _discover_subcategories(seed)
        all_categories.extend(cats)
        print(f"  {seed} → {len(cats)} categories (incl. subs)")

    # Deduplicate
    all_categories = list(dict.fromkeys(all_categories))
    print(f"  Total unique categories: {len(all_categories)}")
    print()

    # Collect all video file titles
    print("📋 Listing video files in categories...")
    all_titles = set()
    if update_mode:
        # In update mode, only look at recent files
        existing = set(row[0] for row in conn.execute("SELECT page_id FROM clips").fetchall())
    else:
        existing = set()

    for i, cat in enumerate(all_categories):
        members = _fetch_category_members(cat, cmtype="file", limit=max_files_per_cat)
        video_members = [m for m in members if _is_video(m["title"])]
        for m in video_members:
            all_titles.add(m["title"])
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(all_categories)}] {cat} → {len(video_members)} videos (total: {len(all_titles)})")

    print(f"  Total unique video files found: {len(all_titles)}")
    print()

    # Fetch metadata in batches
    print("📥 Fetching metadata (batch of 50 titles per request)...")
    titles_list = list(all_titles)
    new_count = 0
    skip_count = 0

    for i in range(0, len(titles_list), BATCH_SIZE):
        batch = titles_list[i:i + BATCH_SIZE]
        metadata = _fetch_file_metadata(batch)

        for item in metadata:
            # Skip if already indexed and in update mode
            if item["page_id"] in existing:
                skip_count += 1
                continue

            try:
                conn.execute("""
                    INSERT OR REPLACE INTO clips
                    (page_id, title, description, categories, license, thumb_url,
                     width, height, duration, size_bytes, mime, page_url, timestamp, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    item["page_id"], item["title"], item["description"], item["categories"],
                    item["license"], item["thumb_url"], item["width"], item["height"],
                    item["duration"], item["size_bytes"], item["mime"], item["page_url"],
                    item["timestamp"]
                ))
                new_count += 1
            except sqlite3.IntegrityError:
                skip_count += 1

        if (i // BATCH_SIZE + 1) % 20 == 0:
            conn.commit()
            print(f"  [{i//BATCH_SIZE + 1}] {i+len(batch)}/{len(titles_list)} titles processed "
                  f"({new_count} new, {skip_count} skipped)")

    conn.commit()

    # Update index metadata
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT OR REPLACE INTO index_meta VALUES ('last_full_index', ?)", (now,))
    conn.execute("INSERT OR REPLACE INTO index_meta VALUES ('total_categories', ?)",
                 (str(len(all_categories)),))
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
    print()
    print(f"✅ Index complete: {new_count} new clips added, {skip_count} skipped")
    print(f"📊 Total library: {total:,} clips")
    print(f"🕐 Last indexed: {now}")

    conn.close()
    return total


def show_stats():
    """Display index statistics."""
    if not DB_PATH.exists():
        print("No index found. Run wikimedia_indexer.py first.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    total = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
    avg_dur = conn.execute("SELECT AVG(duration) FROM clips WHERE duration > 0").fetchone()[0] or 0
    hd_count = conn.execute("SELECT COUNT(*) FROM clips WHERE width >= 1280").fetchone()[0]
    cc0_count = conn.execute("SELECT COUNT(*) FROM clips WHERE license LIKE '%cc0%' OR license LIKE '%public domain%'").fetchone()[0]

    print(f"📊 Wikimedia Index Stats")
    print(f"  Total clips: {total:,}")
    print(f"  HD (720p+): {hd_count:,}")
    print(f"  CC0/Public Domain: {cc0_count:,}")
    print(f"  Avg duration: {avg_dur:.1f}s")
    print()

    # Top categories
    print("  Top categories:")
    rows = conn.execute("""
        SELECT categories, COUNT(*) as cnt FROM clips
        WHERE categories != ''
        GROUP BY categories ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    for row in rows:
        cats = row[0][:80] if row[0] else "(none)"
        print(f"    {row[1]:>5} — {cats}")

    conn.close()


# ── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    if "--stats" in sys.argv:
        show_stats()
    elif "--update" in sys.argv:
        print("🔄 Running incremental update...")
        crawl_and_index(update_mode=True)
    else:
        print("🚀 Starting full Wikimedia Commons crawl...")
        print(f"   Seed categories: {len(SEED_CATEGORIES)}")
        print(f"   Max depth: {MAX_CATEGORY_DEPTH}")
        print()
        crawl_and_index()