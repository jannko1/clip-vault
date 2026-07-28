"""
Free Media Search Engine — aggregates Pexels, Pixabay (video) and Freesound (SFX).
Run: pip install flask requests && python app.py
Open: http://localhost:5000
"""
import json
import os
import secrets
import time
import hmac
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from flask import Flask, jsonify, request, render_template, send_from_directory

from titles import generate_title, clean_title
from dedup import group_duplicates
from keywords import expand_query
from script_parser import parse_script

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Register auth blueprint
from auth import auth_bp
app.register_blueprint(auth_bp)

# Load config — prefer env vars (Vercel), fall back to config.json (local)
CONFIG_PATH = Path(__file__).parent / "config.json"
CONFIG = {}
if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        CONFIG = json.load(f)

PEXELS_KEY = os.environ.get("PEXELS_API_KEY") or CONFIG.get("pexels_api_key", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY") or CONFIG.get("pixabay_api_key", "")
COVERR_KEY = os.environ.get("COVERR_API_KEY") or CONFIG.get("coverr_api_key", "")
VIMEO_TOKEN = os.environ.get("VIMEO_ACCESS_TOKEN") or CONFIG.get("vimeo_access_token", "")
FREESOUND_TOKEN = os.environ.get("FREESOUND_TOKEN") or CONFIG.get("freesound_token", "")
STORYBLOCKS_KEY = os.environ.get("STORYBLOCKS_API_KEY") or CONFIG.get("storyblocks_api_key", "")
STORYBLOCKS_SECRET = os.environ.get("STORYBLOCKS_API_SECRET") or CONFIG.get("storyblocks_api_secret", "")
EUROPEANA_KEY = os.environ.get("EUROPEANA_API_KEY") or CONFIG.get("europeana_api_key", "")
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_PATH") or CONFIG.get("download_path", str(Path(__file__).parent / "downloads")))
try:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    DOWNLOAD_DIR = Path("/tmp") / "downloads"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Search history for learning ──
SEARCH_LOG_PATH = Path(__file__).parent / "data" / "search_history.json"
try:
    SEARCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
except (OSError, PermissionError):
    SEARCH_LOG_PATH = Path("/tmp") / "search_history.json"

def _interleave(*buckets: list) -> list:
    """Interleave items from multiple lists round-robin for fair source distribution."""
    result = []
    max_len = max(len(b) for b in buckets) if buckets else 0
    for i in range(max_len):
        for bucket in buckets:
            if i < len(bucket):
                result.append(bucket[i])
    return result

def _log_search(query: str, result_count: int):
    """Log each search to build a learning dataset."""
    entry = {
        "q": query.lower(),
        "results": result_count,
        "time": time.time(),
    }
    try:
        history = []
        if SEARCH_LOG_PATH.exists():
            history = json.loads(SEARCH_LOG_PATH.read_text(encoding="utf-8") or "[]")
        history.append(entry)
        # Keep last 500 searches
        SEARCH_LOG_PATH.write_text(json.dumps(history[-500:], indent=2), encoding="utf-8")
    except Exception:
        pass  # Never let logging break search

# ── Cache ──────────────────────────────────────────────
CACHE = {}  # {key: (timestamp, data)}
CACHE_TTL = 300  # 5 minutes


def cached_fetch(url: str, headers: dict = None) -> dict:
    """Fetch JSON with 5-minute cache to stay within rate limits."""
    cache_key = url
    now = time.time()
    if cache_key in CACHE and (now - CACHE[cache_key][0]) < CACHE_TTL:
        return CACHE[cache_key][1]
    try:
        hdrs = headers or {}
        hdrs.setdefault("User-Agent", "ClipVault/1.0")
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read())
        CACHE[cache_key] = (now, data)
        return data
    except Exception as e:
        print(f"[API ERROR] {url[:80]}: {e}")
        return {}


# ── VIDEO: Pexels ──────────────────────────────────────

def search_pexels_videos(query: str, per_page: int = 20) -> list:
    if not PEXELS_KEY or PEXELS_KEY.startswith("YOUR_"):
        return []
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page={per_page}"
    data = cached_fetch(url, headers={"Authorization": PEXELS_KEY})
    results = []
    for v in data.get("videos", []):
        files = sorted(v.get("video_files", []), key=lambda f: (f.get("width", 0), f.get("height", 0)), reverse=True)
        best = files[0] if files else {}
        # Find 720p-ish file for preview (target height 720, max width 1280)
        preview_file = best
        for f in files:
            if f.get("height", 0) <= 720 and f.get("width", 0) <= 1280:
                preview_file = f
                break
        results.append({
            "id": f"pexels-{v['id']}",
            "source": "Pexels",
            "source_url": v.get("url", ""),
            "thumbnail": v.get("image", ""),
            "preview": preview_file.get("link", ""),
            "download_url": best.get("link", ""),
            "duration": v.get("duration", 0),
            "width": best.get("width", 0),
            "height": best.get("height", 0),
            "author": v.get("user", {}).get("name", "Unknown"),
            "type": "video",
        })
    return results


# ── VIDEO: Pixabay ─────────────────────────────────────

def search_pixabay_videos(query: str, per_page: int = 20) -> list:
    if not PIXABAY_KEY or PIXABAY_KEY.startswith("YOUR_"):
        return []
    url = f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}&q={urllib.parse.quote(query)}&per_page={per_page}"
    data = cached_fetch(url)
    results = []
    for v in data.get("hits", []):
        videos = v.get("videos", {})
        # Download: highest quality (large). Preview: 720p (medium).
        best = videos.get("large") or videos.get("medium") or videos.get("small") or videos.get("tiny") or {}
        preview_vid = videos.get("medium") or videos.get("small") or videos.get("tiny") or best
        results.append({
            "id": f"pixabay-{v['id']}",
            "source": "Pixabay",
            "source_url": v.get("pageURL", ""),
            "thumbnail": best.get("thumbnail", f"https://i.vimeocdn.com/video/{v.get('picture_id', '')}_640x360.jpg"),
            "preview": preview_vid.get("url", ""),
            "download_url": best.get("url", ""),
            "duration": v.get("duration", 0),
            "width": best.get("width", 0),
            "height": best.get("height", 0),
            "author": v.get("user", "Unknown"),
            "tags": v.get("tags", ""),
            "type": "video",
        })
    return results


# ── VIDEO: Coverr ─────────────────────────────────────

def search_coverr_videos(query: str, per_page: int = 20) -> list:
    if not COVERR_KEY or COVERR_KEY.startswith("YOUR_"):
        return []
    url = f"https://api.coverr.co/videos?query={urllib.parse.quote(query)}&page_size={per_page}&urls=true"
    data = cached_fetch(url, headers={"Authorization": f"Bearer {COVERR_KEY}"})
    results = []
    for v in data.get("hits", []):
        urls = v.get("urls", {})
        results.append({
            "id": f"coverr-{v['id']}",
            "source": "Coverr",
            "source_url": f"https://coverr.co/videos/{v.get('slug', v['id'])}",
            "thumbnail": v.get("poster") or v.get("thumbnail", ""),
            "preview": urls.get("mp4_preview", urls.get("mp4", "")),
            "download_url": urls.get("mp4_download", urls.get("mp4", "")),
            "duration": v.get("duration", 0),
            "width": v.get("max_width", 0),
            "height": v.get("max_height", 0),
            "author": "Coverr",
            "title_raw": v.get("title", ""),
            "description": v.get("description", ""),
            "tags": ", ".join(v.get("tags", [])),
            "type": "video",
        })
    return results


# ── VIDEO: Storyblocks ─────────────────────────────────

def search_storyblocks_videos(query: str, per_page: int = 20) -> list:
    if not STORYBLOCKS_KEY or STORYBLOCKS_KEY.startswith("YOUR_"):
        return []
    try:
        resource = "/api/v2/videos/search"
        expires = str(int(time.time()) + 300)
        hmac_builder = hmac.new(
            (STORYBLOCKS_SECRET + expires).encode('utf-8'),
            resource.encode('utf-8'),
            hashlib.sha256
        )
        hmac_hex = hmac_builder.hexdigest()

        params = {
            'APIKEY': STORYBLOCKS_KEY,
            'EXPIRES': expires,
            'HMAC': hmac_hex,
            'project_id': 'clipvault',
            'user_id': 'jan',
            'keywords': query,
            'results_per_page': str(per_page),
            'sort_by': 'most_relevant'
        }
        url = f"https://api.storyblocks.com{resource}?{urllib.parse.urlencode(params)}"
        # Bypass cached_fetch — use direct call with error visibility
        req = urllib.request.Request(url, headers={"User-Agent": "ClipVault/1.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read())

        if not data:
            return []

        total = data.get("total_results", 0)
        if total == 0:
            return []

        results = []
        for v in data.get("results", []):
            previews = v.get("preview_urls", {})
            preview = previews.get("_720p") or previews.get("_480p") or previews.get("_360p", "")
            results.append({
                "id": f"storyblocks-{v['id']}",
                "source": "Storyblocks",
                "source_url": f"https://www.storyblocks.com/video/stock/{v.get('id','')}",
                "thumbnail": v.get("thumbnail_url", ""),
                "preview": preview,
                "download_url": "",
                "duration": v.get("duration", 0),
                "width": 1920,
                "height": 1080,
                "author": "Storyblocks",
                "description": v.get("title", ""),
                "type": "video",
            })
        return results
    except Exception as e:
        return []


# ── PHOTOS: Pexels ─────────────────────────────────────

def search_pexels_photos(query: str, per_page: int = 20) -> list:
    if not PEXELS_KEY or PEXELS_KEY.startswith("YOUR_"):
        return []
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page={per_page}"
    data = cached_fetch(url, headers={"Authorization": PEXELS_KEY})
    results = []
    for p in data.get("photos", []):
        results.append({
            "id": f"pexels-photo-{p['id']}",
            "source": "Pexels",
            "source_url": p.get("url", ""),
            "thumbnail": p.get("src", {}).get("medium", ""),
            "preview": p.get("src", {}).get("large", ""),
            "download_url": p.get("src", {}).get("original", ""),
            "duration": 0,
            "width": p.get("width", 0),
            "height": p.get("height", 0),
            "author": p.get("photographer", "Unknown"),
            "alt": p.get("alt", ""),
            "type": "image",
        })
    return results


# ── PHOTOS: Pixabay ────────────────────────────────────

def search_pixabay_images(query: str, per_page: int = 20) -> list:
    if not PIXABAY_KEY or PIXABAY_KEY.startswith("YOUR_"):
        return []
    url = f"https://pixabay.com/api/?key={PIXABAY_KEY}&q={urllib.parse.quote(query)}&per_page={per_page}&image_type=photo,illustration,vector"
    data = cached_fetch(url)
    results = []
    for p in data.get("hits", []):
        results.append({
            "id": f"pixabay-img-{p['id']}",
            "source": "Pixabay",
            "source_url": p.get("pageURL", ""),
            "thumbnail": p.get("webformatURL", ""),
            "preview": p.get("largeImageURL", ""),
            "download_url": p.get("largeImageURL", ""),
            "duration": 0,
            "width": p.get("imageWidth", 0),
            "height": p.get("imageHeight", 0),
            "author": p.get("user", "Unknown"),
            "tags": p.get("tags", ""),
            "type": "image",
        })
    return results


# ── IMAGE: Wikimedia Commons ─────────────────────────

def _wikimedia_fetch(url: str) -> dict:
    """Fetch from Wikimedia API with rate limiting, retry on 429."""
    import time as _time
    for attempt in range(3):
        _time.sleep(0.3)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ClipVault/2.0 (https://clipvault.app; jan@clipvault.app)"})
            with urllib.request.urlopen(req, timeout=10) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _time.sleep(2 ** attempt)  # Exponential backoff
                continue
            return {}
        except Exception:
            return {}
    return {}


def _extract_visual_keywords(query: str) -> list:
    """Extract visual nouns from a descriptive query.
    Strips stop words, film terms, camera directions — keeps only what you'd SEE.
    Example: 'close up aerial drone shot of mountains at golden hour' → ['mountains']"""
    stop_words = {
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might",
        "can", "shall", "you", "i", "me", "my", "we", "our", "they", "them",
        "this", "that", "these", "those", "what", "which", "who", "how", "when",
        "and", "or", "but", "not", "no", "so", "if", "then", "than", "too",
        "very", "just", "about", "up", "out", "there", "here", "all", "each",
        "every", "both", "few", "more", "most", "other", "some", "such",
        "only", "own", "same", "into", "over", "under", "again", "once",
        "now", "also", "get", "got", "make", "made", "like", "know", "see",
        "look", "want", "need", "come", "take", "give", "use", "find",
        "still", "well", "way", "even", "new", "good", "any", "thing",
        "one", "two", "time", "day", "really", "much", "back", "down",
        "right", "left", "around", "never", "always", "ever", "going",
        "yeah", "oh", "um", "er", "ah", "hey", "ok", "alright", "yes",
        "his", "her", "him", "our", "us", "myself", "yourself",
        # Film/camera terms — not visual content
        "shot", "scene", "closeup", "close", "medium", "wide", "angle",
        "slow", "fast", "motion", "movement", "camera", "footage",
        "color", "tone", "mood", "lighting", "style", "vibe", "feel",
        "shallow", "deep", "depth", "field", "focus", "soft", "hard",
        "warm", "cold", "golden", "blue", "natural", "sunlight",
        "handheld", "aerial", "drone", "product", "studio", "sun",
        "hour", "light", "background", "foreground", "cinematic",
        "4k", "hd", "high", "quality", "view", "looking", "facing",
        "sipping", "drinking", "walking", "running", "standing",
        "sitting", "holding", "carrying", "pulling", "pushing",
        "morning", "evening", "afternoon", "night", "nostalgia",
        "nostalgic", "retro", "vintage", "modern", "contemporary",
    }
    keywords = []
    for word in query.lower().replace(",", " ").replace(".", " ").replace("-", " ").split():
        w = word.strip().rstrip("s")  # Basic singularization
        if w and len(w) > 1 and w not in stop_words:
            keywords.append(w)
    # Remove duplicates while preserving order
    seen = set()
    return [kw for kw in keywords if not (kw in seen or seen.add(kw))]


# ── Wikidata entity cache ───────────────────────────────

_WIKIDATA_CACHE = {}


def _wikidata_lookup(term: str) -> str | None:
    """Resolve a term to a Wikidata Q-ID for semantic search."""
    if term in _WIKIDATA_CACHE:
        return _WIKIDATA_CACHE[term]
    try:
        url = (
            "https://www.wikidata.org/w/api.php?action=wbsearchentities"
            f"&search={urllib.parse.quote(term)}&language=en&limit=1&format=json&origin=*"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ClipVault/1.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read())
        results = data.get("search", [])
        if results:
            qid = results[0].get("id", "")
            _WIKIDATA_CACHE[term] = qid
            return qid
    except Exception:
        pass
    _WIKIDATA_CACHE[term] = None
    return None


# ── Search helpers ──────────────────────────────────────

def _search_titles(query_str: str, limit: int = 20) -> list:
    """Search Wikimedia and return file titles."""
    base = "https://commons.wikimedia.org/w/api.php"
    url = (
        f"{base}?action=query&generator=search&gsrsearch="
        f"{urllib.parse.quote(query_str)}&gsrnamespace=6&gsrlimit={limit}"
        f"&format=json&origin=*"
    )
    data = _wikimedia_fetch(url)
    pages = data.get("query", {}).get("pages", {})
    return [p.get("title", "") for p in pages.values() if p.get("title", "").startswith("File:")]


def _fetch_metadata_for_titles(titles: list[str]) -> list:
    """Fetch full metadata for file titles, return normalized results."""
    if not titles:
        return []
    base = "https://commons.wikimedia.org/w/api.php"
    results = []

    for batch_start in range(0, len(titles), 10):
        batch = titles[batch_start:batch_start + 10]
        encoded = "|".join(urllib.parse.quote(t, safe="") for t in batch)
        url = (
            f"{base}?action=query&titles={encoded}"
            f"&prop=imageinfo&iiprop=extmetadata|url|size|mime|mediatype|metadata"
            f"&iiurlwidth=640&format=json&origin=*"
        )
        data = _wikimedia_fetch(url)
        for page_id, page in data.get("query", {}).get("pages", {}).items():
            imageinfo = page.get("imageinfo", [])
            if not imageinfo:
                continue
            info = imageinfo[0]
            extmeta = info.get("extmetadata", {})
            license_short = (extmeta.get("LicenseShortName", {}) or {}).get("value", "").lower()

            # License filter
            safe_licenses = {"cc0", "cc by", "cc by-sa", "public domain", "pd", "cc-zero"}
            if license_short and not any(s in license_short for s in safe_licenses):
                continue

            mime = info.get("mime", "")
            mediatype = (info.get("mediatype") or "").upper()
            is_video = "VIDEO" in mediatype or "video" in mime or "ogg" in mime

            duration = 0
            width = info.get("width", 0)
            height = info.get("height", 0)
            for meta in info.get("metadata", []):
                name = meta.get("name", "")
                if name == "playtime_seconds":
                    try:
                        duration = float(meta.get("value", 0))
                    except (ValueError, TypeError):
                        pass
                elif name == "video" and isinstance(meta.get("value"), list):
                    for vitem in meta["value"]:
                        if vitem.get("name") == "resolution_x":
                            try: width = int(vitem.get("value", width))
                            except: pass
                        elif vitem.get("name") == "resolution_y":
                            try: height = int(vitem.get("value", height))
                            except: pass

            raw_url = info.get("url", "")
            thumb_url = info.get("thumburl", "")
            if is_video:
                preview_url = raw_url
                if not thumb_url and raw_url:
                    thumb_url = raw_url + "?width=640"
            else:
                preview_url = thumb_url or raw_url

            raw_title = page.get("title", "").replace("File:", "")
            clean_name = raw_title.rsplit(".", 1)[0].replace("_", " ") if "." in raw_title else raw_title.replace("_", " ")
            author = (extmeta.get("Artist", {}) or {}).get("value", "").strip() or "Wikimedia Commons"

            results.append({
                "id": f"wikimedia-{page_id}",
                "source": "Wikimedia",
                "source_url": info.get("descriptionurl", ""),
                "thumbnail": thumb_url,
                "preview": preview_url,
                "download_url": raw_url,
                "duration": duration,
                "width": width,
                "height": height,
                "author": author,
                "description": extmeta.get("ImageDescription", {}).get("value", "") or clean_name,
                "title_raw": clean_name,
                "license": license_short,
                "type": "video" if is_video else "image",
            })
    return results


# ── MAIN SEARCH: 3-Layer Cascade ─────────────────────────

def search_wikimedia(query: str, per_page: int = 20) -> list:
    """
    Search Wikimedia Commons with 3-layer cascade for maximum hit rate:
    Layer 1: Query decomposition — search each visual keyword independently
    Layer 2: SDC depicts filter — boost files with structured data annotations
    Layer 3: Wikidata entity lookup — semantic precision via Q-ID search
    Layer 4 (fallback): Original full-phrase gsrsearch
    """
    keywords = _extract_visual_keywords(query)
    
    # ── Layer 1: Decomposed keyword search ──
    all_titles = {}
    for kw in keywords:
        for title in _search_titles(f"{kw} filetype:video", per_page):
            all_titles[title] = all_titles.get(title, 0) + 1
        # Also search without video filter for broader coverage
        for title in _search_titles(kw, per_page // 2):
            if title not in all_titles:
                all_titles[title] = 1
    
    # ── Layer 2: SDC depicts filter (quality boost) ──
    for kw in keywords[:3]:  # Only top 3 keywords for SDC
        for title in _search_titles(f"{kw} haswbstatement:P180 filetype:video", per_page // 2):
            all_titles[title] = all_titles.get(title, 0) + 3  # SDC bonus
    
    # ── Layer 3: Wikidata entity precision ──
    if keywords:
        qid = _wikidata_lookup(keywords[0])
        if qid:
            for title in _search_titles(f"haswbstatement:P180={qid} filetype:video", per_page):
                all_titles[title] = all_titles.get(title, 0) + 5  # Entity bonus
    
    # ── Fallback: Full phrase search (if cascade returned < 3 results) ──
    if len(all_titles) < 3:
        for title in _search_titles(f"{query} filetype:video", per_page):
            all_titles[title] = all_titles.get(title, 0) + 2
        for title in _search_titles(query, per_page):
            if title not in all_titles:
                all_titles[title] = 1
    
    # ── Rank by score, fetch metadata, filter ──
    ranked = sorted(all_titles.items(), key=lambda x: x[1], reverse=True)
    top_titles = [t for t, score in ranked[:per_page * 2]]
    
    results = _fetch_metadata_for_titles(top_titles)
    
    # Secondary relevance filter (looser than before — cascade already pre-filters)
    scored = [(r, _relevance_score(query, r.get("title_raw", ""), r.get("description", ""))) for r in results]
    scored = [(r, s) for r, s in scored if s >= 0.20 or query.lower() in r.get("title_raw", "").lower()]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    return [r for r, s in scored[:per_page]]


def _relevance_score(query: str, title: str, description: str = "") -> float:
    """Score result relevance to query. 0.0 = irrelevant, 1.0 = perfect."""
    keywords = _extract_visual_keywords(query)
    if not keywords:
        return 0.5
    text = (title + " " + description).lower()
    matches = sum(1 for kw in keywords if kw in text)
    ratio = matches / len(keywords)
    if query.lower() in text:
        ratio = min(1.0, ratio + 0.3)
    return ratio


# ── IMAGE: Europeana ──────────────────────────────────

def search_europeana(query: str, per_page: int = 20) -> list:
    """Search Europeana for royalty-free images AND videos (needs API key).
    Uses reusability=open (PD, CC0, CC-BY, CC-BY-SA) + TYPE:VIDEO/IMAGE facets."""
    if not EUROPEANA_KEY or EUROPEANA_KEY.startswith("YOUR_"):
        return []
    
    results = []
    # Search both images and videos
    for type_filter in ["", "&qf=TYPE:VIDEO"]:
        url = (
            f"https://api.europeana.eu/record/v2/search.json"
            f"?wskey={EUROPEANA_KEY}"
            f"&query={urllib.parse.quote(query)}"
            f"&reusability=open"
            f"&media=true&thumbnail=true"
            f"&rows={per_page // 2}"
            f"{type_filter}"
        )
        data = cached_fetch(url)
        
        for item in data.get("items", []):
            previews = item.get("edmPreview", [])
            thumb = previews[0] if previews else ""
            item_type = item.get("type", "").upper()
            media_type = "video" if ("VIDEO" in item_type or type_filter) else "image"
            
            results.append({
                "id": f"europeana-{item.get('id', '')}",
                "source": "Europeana",
                "source_url": item.get("guid", ""),
                "thumbnail": thumb,
                "preview": thumb,
                "download_url": (item.get("edmIsShownBy", [None]) or [None])[0] or thumb,
                "duration": 0,
                "width": 0,
                "height": 0,
                "author": (item.get("dataProvider", [""]) or [""])[0],
                "license": (item.get("rights", [""]) or [""])[0],
                "type": media_type,
            })
    return results


# ── VIDEO: Vimeo REMOVED — permanently geo-blocked from Slovenia ─


# ── SFX: Freesound ─────────────────────────────────────

def search_freesound(query: str, per_page: int = 20) -> list:
    if not FREESOUND_TOKEN or FREESOUND_TOKEN.startswith("YOUR_"):
        return []
    url = (
        f"https://freesound.org/apiv2/search/text/?"
        f"query={urllib.parse.quote(query)}"
        f"&token={FREESOUND_TOKEN}"
        f"&page_size={per_page}"
        f"&fields=id,name,previews,download,duration,username,tags,license"
    )
    data = cached_fetch(url)
    results = []
    for s in data.get("results", []):
        previews = s.get("previews", {})
        preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3") or ""
        results.append({
            "id": f"freesound-{s['id']}",
            "source": "Freesound",
            "source_url": f"https://freesound.org/people/{s.get('username', '')}/sounds/{s['id']}/",
            "thumbnail": "",
            "preview": preview_url,
            "download_url": preview_url,  # Preview HQ is downloadable without OAuth2
            "duration": s.get("duration", 0),
            "width": 0,
            "height": 0,
            "author": s.get("username", "Unknown"),
            "tags": ", ".join(s.get("tags", [])[:5]),
            "license": s.get("license", ""),
            "type": "audio",
        })
    return results


# ── ROUTES ─────────────────────────────────────────────

@app.route("/api/health")
def health():
    """Health check — no dependencies."""
    import os as _os
    return jsonify({
        "status": "ok",
        "sources": ["pexels", "pixabay", "coverr", "storyblocks", "wikimedia", "europeana"],
        "storyblocks_key": bool(_os.environ.get("STORYBLOCKS_API_KEY", "")),
        "storyblocks_secret": bool(_os.environ.get("STORYBLOCKS_API_SECRET", ""))
    })


@app.route("/api/test-storyblocks")
def test_storyblocks():
    """Direct Storyblocks API test."""
    try:
        resource = "/api/v2/videos/search"
        expires = str(int(time.time()) + 300)
        hmac_builder = hmac.new(
            (STORYBLOCKS_SECRET + expires).encode('utf-8'),
            resource.encode('utf-8'),
            hashlib.sha256
        )
        hmac_hex = hmac_builder.hexdigest()
        params = {
            'APIKEY': STORYBLOCKS_KEY,
            'EXPIRES': expires,
            'HMAC': hmac_hex,
            'project_id': 'clipvault',
            'user_id': 'jan',
            'keywords': 'ocean',
            'results_per_page': '3',
            'sort_by': 'most_relevant'
        }
        url = f"https://api.storyblocks.com{resource}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "ClipVault/1.0"})
        with urllib.request.urlopen(req, timeout=15) as res:
            raw = res.read().decode()
            data = json.loads(raw)
        return jsonify({
            "status": "ok",
            "total": data.get("total_results", 0),
            "keys": list(data.keys()),
            "raw_preview": str(data)[:500]
        })
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e), "type": type(e).__name__})

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search")
def search_page():
    return render_template("index.html")


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/terms")
def terms():
    return render_template("footer.html", page="terms")


@app.route("/privacy")
def privacy():
    return render_template("footer.html", page="privacy")


@app.route("/license")
def license_page():
    return render_template("footer.html", page="license")


@app.route("/imprint")
def imprint():
    return render_template("footer.html", page="imprint")


@app.route("/cookies")
def cookies():
    return render_template("footer.html", page="cookies")


@app.route("/partner")
def partner():
    return render_template("footer.html", page="partner")


@app.route("/report")
def report():
    return render_template("footer.html", page="report")


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    media_type = request.args.get("type", "video")  # video | audio
    single_source = request.args.get("source", "")  # filter to one source: wikimedia, pexels, etc.

    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    raw_results = []

    if media_type == "video":
        # Expand query and search all variations (VIDEO ONLY — no images)
        queries = expand_query(query)
        seen_ids = set()
        source_buckets = {"Pexels": [], "Pixabay": [], "Coverr": [], "Storyblocks": [], "Wikimedia": [], "Europeana": []}

        for q in queries:
            if not single_source or single_source == "pexels":
                for r in search_pexels_videos(q):
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        source_buckets["Pexels"].append(r)
            if not single_source or single_source == "pixabay":
                for r in search_pixabay_videos(q):
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        source_buckets["Pixabay"].append(r)
            if not single_source or single_source == "coverr":
                for r in search_coverr_videos(q):
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        source_buckets["Coverr"].append(r)
            if not single_source or single_source == "storyblocks":
                try:
                    for r in search_storyblocks_videos(q):
                        if r["id"] not in seen_ids:
                            seen_ids.add(r["id"])
                            source_buckets["Storyblocks"].append(r)
                except Exception:
                    pass
            if not single_source or single_source == "wikimedia":
                try:
                    for r in search_wikimedia(q):
                        if r["id"] not in seen_ids:
                            seen_ids.add(r["id"])
                            source_buckets["Wikimedia"].append(r)
                except Exception:
                    pass
            if not single_source or single_source == "europeana":
                try:
                    for r in search_europeana(q):
                        if r["id"] not in seen_ids:
                            seen_ids.add(r["id"])
                            source_buckets["Europeana"].append(r)
                except Exception:
                    pass
        # ── Interleave results round-robin: all 6 sources ──
        raw_results = _interleave(source_buckets["Pexels"],
                                  source_buckets["Pixabay"],
                                  source_buckets["Coverr"],
                                  source_buckets["Storyblocks"],
                                  source_buckets["Wikimedia"],
                                  source_buckets["Europeana"])

        # ── Log search for future analysis ──
        _log_search(query, len(seen_ids))
    elif media_type == "audio":
        queries = expand_query(query)
        seen_ids = set()
        for q in queries:
            for r in search_freesound(q):
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    raw_results.append(r)

    # ── Apply titles ──
    for r in raw_results:
        r["title"] = clean_title(generate_title(r))

    # ── Group duplicates ──
    groups = group_duplicates(raw_results)

    # ── Build response ──
    result_groups = []
    for g in groups[:42]:  # Cap at 42 groups (6 rows of 7) for performance
        result_groups.append({
            "has_variants": g["has_variants"],
            "variant_count": g["variant_count"],
            "primary": g["primary"],
            "variants": g["variants"],
        })

    total_cards = len(result_groups)
    total_clips = len(raw_results)
    total_available = len(groups)

    return jsonify({
        "query": query,
        "type": media_type,
        "total_cards": total_cards,
        "total_clips": total_clips,
        "groups": result_groups,
    })


@app.route("/api/parse-script", methods=["POST"])
def parse_script_endpoint():
    """Parse an ad script, extract keywords per scene, and find matching clips."""
    data = request.get_json(silent=True) or {}
    script_text = data.get("script", "").strip()
    media_type = data.get("type", "video")

    if not script_text:
        return jsonify({"error": "No script text provided"}), 400

    scenes = parse_script(script_text)
    single_source = data.get("source", "")

    import random

    # Search clips for each scene
    for scene in scenes:
        query = scene["search_query"]
        if not query:
            scene["clips"] = []
            continue

        raw = []
        if media_type == "video":
            queries = expand_query(query)
            seen = set()
            
            if single_source == "wikimedia":
                # Wiki-only mode: search only Wikimedia
                for q in queries:
                    for r in search_wikimedia(q):
                        if r["id"] not in seen:
                            seen.add(r["id"])
                            r["title"] = generate_title(r)
                            raw.append(r)
            else:
                # All sources mode
                src = {"Pexels": [], "Pixabay": [], "Coverr": []}
                for q in queries:
                    for r in search_pexels_videos(q):
                        if r["id"] not in seen:
                            seen.add(r["id"])
                            r["title"] = generate_title(r)
                            src["Pexels"].append(r)
                    for r in search_pixabay_videos(q):
                        if r["id"] not in seen:
                            seen.add(r["id"])
                            r["title"] = generate_title(r)
                            src["Pixabay"].append(r)
                    for r in search_coverr_videos(q):
                        if r["id"] not in seen:
                            seen.add(r["id"])
                            r["title"] = generate_title(r)
                            src["Coverr"].append(r)
                raw = _interleave(src["Pexels"], src["Pixabay"], src["Coverr"])
                # Append Storyblocks + Wikimedia
                for q in queries:
                    try:
                        for r in search_storyblocks_videos(q):
                            if r["id"] not in seen:
                                seen.add(r["id"])
                                r["title"] = generate_title(r)
                                raw.append(r)
                    except Exception:
                        pass
                for q in queries:
                    for r in search_wikimedia(q):
                        if r["id"] not in seen:
                            seen.add(r["id"])
                            r["title"] = generate_title(r)
                            raw.append(r)
        else:
            queries = expand_query(query)
            seen = set()
            for q in queries:
                for r in search_freesound(q):
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        r["title"] = generate_title(r)
                        raw.append(r)

        # Shuffle groups to mix sources, then take top 7 (5 video + 2 image)
        grouped = group_duplicates(raw)
        random.shuffle(grouped)
        videos = [g for g in grouped if g["primary"]["type"] == "video"]
        images = [g for g in grouped if g["primary"]["type"] != "video"]
        scene["clips"] = (videos[:5] + images[:2]) if videos else grouped[:7]
        if not scene["clips"]:
            scene["clips"] = grouped[:7]
        scene["total_found"] = len(grouped)

    return jsonify({
        "script": script_text,
        "scenes": scenes,
        "scene_count": len(scenes),
        "media_type": media_type,
    })


@app.route("/api/download-audio")
def download_audio():
    """Download and optimize audio: normalize volume, prevent clipping, basic denoise."""
    url = request.args.get("url", "")
    filename = request.args.get("filename", "audio")
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400

    import subprocess
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return jsonify({"error": "ffmpeg not found"}), 500

    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")[:60]
    raw_path = DOWNLOAD_DIR / f"{safe_name}_raw.tmp"
    out_path = DOWNLOAD_DIR / f"{safe_name}_opt.mp3"

    try:
        # Step 1: Download raw audio
        req = urllib.request.Request(url, headers={"User-Agent": "ClipVault/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_path.write_bytes(resp.read())

        # Step 2: Optimize with ffmpeg
        # - loudnorm: EBU R128 normalization (target -16 LUFS, safe for web)
        # - highpass at 30Hz: remove sub-bass rumble
        # - lowpass at 18000Hz: remove ultrasonic noise
        # - afade: tiny fade in/out to prevent clicks
        # - volume检测: prevent clipping with limiter
        cmd = [
            ffmpeg, "-y", "-i", str(raw_path),
            "-af",
            "highpass=f=30,lowpass=f=18000,"
            "loudnorm=I=-16:LRA=11:TP=-1.5,"
            "afade=t=in:d=0.01,afade=t=out:d=0.02,"
            "volume=-0.5dB",
            "-ar", "44100",
            "-b:a", "192k",
            "-f", "mp3",
            str(out_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Cleanup raw
        raw_path.unlink(missing_ok=True)

        if result.returncode != 0 or not out_path.exists():
            # Fallback: return raw file
            raw_copy = DOWNLOAD_DIR / f"{safe_name}.mp3"
            shutil.copy(str(raw_path) if raw_path.exists() else url, str(raw_copy))
            return jsonify({
                "success": True,
                "path": str(raw_copy),
                "size": raw_copy.stat().st_size if raw_copy.exists() else 0,
                "optimized": False,
            })

        return jsonify({
            "success": True,
            "path": str(out_path),
            "size": out_path.stat().st_size,
            "optimized": True,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Audio processing timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def download():
    """Proxy download to avoid CORS and save locally."""
    url = request.args.get("url", "")
    filename = request.args.get("filename", "download")
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MediaSearch/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            # Determine extension from content-type
            ct = resp.headers.get("Content-Type", "")
            ext = ".mp4"
            if "mp4" in ct:
                ext = ".mp4"
            elif "mpeg" in ct or "mp3" in ct:
                ext = ".mp3"
            elif "wav" in ct:
                ext = ".wav"
            elif "ogg" in ct:
                ext = ".ogg"

            safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")[:60]
            out_path = DOWNLOAD_DIR / f"{safe_name}{ext}"
            out_path.write_bytes(resp.read())

            return jsonify({
                "success": True,
                "path": str(out_path),
                "size": out_path.stat().st_size,
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def status():
    """Check which APIs are configured."""
    return jsonify({
        "pexels_videos": bool(PEXELS_KEY and not PEXELS_KEY.startswith("YOUR_")),
        "pixabay_videos": bool(PIXABAY_KEY and not PIXABAY_KEY.startswith("YOUR_")),
        "coverr": bool(COVERR_KEY and not COVERR_KEY.startswith("YOUR_")),
        "pexels_photos": bool(PEXELS_KEY and not PEXELS_KEY.startswith("YOUR_")),
        "pixabay_photos": bool(PIXABAY_KEY and not PIXABAY_KEY.startswith("YOUR_")),
        "freesound": bool(FREESOUND_TOKEN and not FREESOUND_TOKEN.startswith("YOUR_")),
    })


if __name__ == "__main__":
    print("=" * 50)
    print("  🎬 Free Media Search Engine")
    print(f"  → http://localhost:5000")
    print(f"  Downloads → {DOWNLOAD_DIR}")
    status = []
    if PEXELS_KEY and not PEXELS_KEY.startswith("YOUR_"):
        status.append("✅ Pexels")
    else:
        status.append("❌ Pexels (set key in config.json)")
    if PIXABAY_KEY and not PIXABAY_KEY.startswith("YOUR_"):
        status.append("✅ Pixabay")
    else:
        status.append("❌ Pixabay (set key in config.json)")
    if COVERR_KEY and not COVERR_KEY.startswith("YOUR_"):
        status.append("✅ Coverr")
    else:
        status.append("❌ Coverr (set key in config.json)")

    if FREESOUND_TOKEN and not FREESOUND_TOKEN.startswith("YOUR_"):
        status.append("✅ Freesound")
    else:
        status.append("❌ Freesound (set token in config.json)")
    print("  " + " | ".join(status))
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5000)
