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
        expires = str(int(time.time()) + 300)  # 5 min expiry
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
        data = cached_fetch(url)

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
                "download_url": "",  # Storyblocks API doesn't provide direct download for non-licensed
                "duration": v.get("duration", 0),
                "width": 1920,  # Storyblocks doesn't return dimensions in search
                "height": 1080,
                "author": "Storyblocks",
                "description": v.get("title", ""),
                "type": "video",
            })
        return results
    except Exception as e:
        print(f"[Storyblocks API Error] {e}")
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


# ── VIDEO: Vimeo REMOVED — permanently geo-blocked from Slovenia (HTTP 404 on every call) ─


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
        "sources": ["pexels", "pixabay", "coverr", "storyblocks"],
        "storyblocks_key": bool(_os.environ.get("STORYBLOCKS_API_KEY", "")),
        "storyblocks_secret": bool(_os.environ.get("STORYBLOCKS_API_SECRET", ""))
    })

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

    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    raw_results = []

    if media_type == "video":
        # Expand query and search all variations (VIDEO ONLY — no images)
        queries = expand_query(query)
        seen_ids = set()
        source_buckets = {"Pexels": [], "Pixabay": [], "Coverr": [], "Storyblocks": []}

        for q in queries:
            for r in search_pexels_videos(q):
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    source_buckets["Pexels"].append(r)
            for r in search_pixabay_videos(q):
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    source_buckets["Pixabay"].append(r)
            for r in search_coverr_videos(q):
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    source_buckets["Coverr"].append(r)
            try:
                for r in search_storyblocks_videos(q):
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        source_buckets["Storyblocks"].append(r)
            except Exception:
                pass  # Storyblocks unavailable — continue with other sources
        # ── Interleave results round-robin: Pexels, Pixabay, Coverr, Storyblocks ──
        raw_results = _interleave(source_buckets["Pexels"],
                                  source_buckets["Pixabay"],
                                  source_buckets["Coverr"],
                                  source_buckets["Storyblocks"])

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
        else:
            queries = expand_query(query)
            seen = set()
            for q in queries:
                for r in search_freesound(q):
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        r["title"] = generate_title(r)
                        raw.append(r)

        # Shuffle groups to mix sources, then take top 7 videos only
        grouped = group_duplicates(raw)
        random.shuffle(grouped)
        videos = [g for g in grouped if g["primary"]["type"] == "video"]
        scene["clips"] = videos[:7] if videos else grouped[:7]
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
