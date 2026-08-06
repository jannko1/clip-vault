"""
Wikimedia Preview URLs Backfill — fetches real transcode derivatives for every
indexed clip and stores the best preview URL (prefer 720p → 480p → 240p → original).

Run: python wikimedia_backfill_previews.py
"""
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "wikimedia_index.db"
USER_AGENT = "ClipVault/1.0 (https://clipvault.app; jan@clipvault.app)"
BATCH_SIZE = 25  # videoinfo derivatives are heavy — smaller batches
REQUEST_DELAY = 0.3

def fetch_derivatives(titles):
    """Fetch videoinfo derivatives for a batch of titles."""
    title_str = "|".join(titles)
    url = (
        "https://commons.wikimedia.org/w/api.php?"
        "action=query&format=json&formatversion=2"
        f"&prop=videoinfo&viprop=derivatives&titles={urllib.parse.quote(title_str)}"
    )
    for attempt in range(3):
        time.sleep(REQUEST_DELAY * (attempt + 1))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** (attempt + 2))
                continue
            return {}
        except Exception:
            if attempt < 2:
                time.sleep(1)
                continue
            return {}
    return {}

def pick_best_preview(derivs, filename=""):
    """Pick the best preview: prefer 720p, then 480p, then 240p.
    Skip the original file (huge). Fall back to a deterministic 480p transcode URL."""
    # Filter out originals — they're massive files, useless for preview
    real_derivs = [d for d in (derivs or []) if "utm_content=original" not in d.get("src", "")]
    
    if real_derivs:
        # Sort: prefer 720p exactly, then closest below
        def score(d):
            w = d.get("width", 0) or 0
            h = d.get("height", 0) or 0
            if w == 1280 or h == 720:
                return 0
            if w <= 854 or h <= 480:  # 480p or less
                return 1
            if w <= 1280 or h <= 720:
                return 2
            return 3  # >720p (1080p etc) — heavy for preview
        best = min(real_derivs, key=score)
        return best.get("src", "")

    # No transcodes listed — construct a deterministic 480p transcode URL
    # (Wikimedia generates these on demand; frontend hides video if 404)
    if filename:
        fn = filename.replace("File:", "").replace(" ", "_")
        import hashlib
        h = hashlib.md5(fn.encode()).hexdigest()
        return (f"https://upload.wikimedia.org/wikipedia/commons/transcoded/"
                f"{h[0]}/{h[:2]}/{fn}/{fn}.480p.vp9.webm")
    return ""

def main():
    conn = sqlite3.connect(str(DB_PATH))
    # Add preview_url column if missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clips)").fetchall()]
    if "preview_url" not in cols:
        conn.execute("ALTER TABLE clips ADD COLUMN preview_url TEXT DEFAULT ''")
        conn.commit()
        print("✅ Added preview_url column")

    # Get all titles (exclude .ogv maybe, but try all)
    rows = conn.execute("SELECT page_id, title FROM clips").fetchall()
    print(f"📊 Backfilling {len(rows)} clips...")

    updated = 0
    skipped = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        titles = [r[1] for r in batch]

        data = fetch_derivatives(titles)
        pages = data.get("query", {}).get("pages", [])

        title_to_page = {}
        for p in pages:
            vi = (p.get("videoinfo") or [{}])[0]
            derivs = vi.get("derivatives", [])
            title_to_page[p["title"]] = derivs

        for page_id, title in batch:
            derivs = title_to_page.get(title, [])
            preview = pick_best_preview(derivs, filename=title)
            if preview:
                conn.execute("UPDATE clips SET preview_url = ? WHERE page_id = ?",
                             (preview, page_id))
                updated += 1
            else:
                skipped += 1

        if (i // BATCH_SIZE + 1) % 10 == 0:
            conn.commit()
            print(f"  [{i//BATCH_SIZE + 1}] {min(i+BATCH_SIZE, len(rows))}/{len(rows)} "
                  f"({updated} updated, {skipped} no preview)")

    conn.commit()
    total_preview = conn.execute(
        "SELECT COUNT(*) FROM clips WHERE preview_url != ''"
    ).fetchone()[0]
    print(f"\n✅ Done: {updated} clips got preview URLs, {skipped} skipped")
    print(f"📊 Total with previews: {total_preview}/{len(rows)}")
    conn.close()

if __name__ == "__main__":
    main()