"""
Title generation for video/audio search results.
Creates human-readable titles from tags, descriptions, or filenames.
"""
import re


def generate_title(item: dict) -> str:
    """
    Generate a clean, readable title from whatever metadata we have.
    
    Priority:
    1. API-provided title_raw (Coverr, Freesound name)
    2. API-provided title/description (if good)
    3. Tags joined into a sentence
    4. Fallback: source + ID
    """
    # If there's a real title, use it directly
    if item.get("title_raw"):
        return item["title_raw"]
    
    source = item.get("source", "")

    # Pexels often doesn't provide titles — use URL slug
    if source == "Pexels":
        return _from_pexels(item)

    # Pixabay provides tags
    if source == "Pixabay":
        return _from_tags(item)

    # Freesound provides name + tags
    if source == "Freesound":
        return _from_freesound(item)

    return _fallback(item)


def _from_pexels(item: dict) -> str:
    """Pexels: extract from URL path or use tags if available."""
    url = item.get("source_url", "")
    # URL like: https://www.pexels.com/video/drone-flying-over-mountains-123456/
    if url:
        slug = url.rstrip("/").split("/")[-2] if "/video/" in url else ""
        if slug and not slug.isdigit():
            # Convert slug to title: "drone-flying-over-mountains" → "Drone flying over mountains"
            title = slug.replace("-", " ").strip()
            if len(title) > 3:
                return _capitalize(title)

    # Try tags if available
    tags = item.get("tags", "")
    if tags:
        return _from_tags_string(tags)

    return _fallback(item)


def _from_pixabay_tags(raw_tags: str) -> str:
    """Pixabay tags: 'nature, mountains, drone, aerial' → 'Aerial drone over mountain nature'"""
    tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    if not tags:
        return None
    
    # Pick top 3-4 meaningful tags and arrange them naturally
    meaningful = [t for t in tags if len(t) > 2 and not t.isdigit()]
    selected = meaningful[:4]
    
    if not selected:
        return None

    # Build a natural-sounding phrase
    if len(selected) >= 3:
        # Try: "adjective noun verbing noun" pattern
        title = " ".join(selected)
    else:
        title = " ".join(selected)

    return _capitalize(title)


def _from_tags(item: dict) -> str:
    """Generate title from tags (Pixabay, generic)."""
    tags = item.get("tags", "")
    if tags:
        title = _from_pixabay_tags(tags)
        if title:
            return title
    
    return _fallback(item)


def _from_freesound(item: dict) -> str:
    """Freesound: has name + tags."""
    name = item.get("name") or item.get("author", "")
    tags = item.get("tags", "")
    
    if name and len(name) > 2:
        title = name
        if tags:
            # Add context from tags if name is vague
            tag_words = [t.strip() for t in tags.split(",") if t.strip() and t.strip().lower() not in title.lower()]
            if tag_words:
                title = f"{title} — {', '.join(tag_words[:2])}"
        return _capitalize(title)
    
    if tags:
        return _from_tags_string(tags)
    
    return _fallback(item)


def _from_tags_string(tags: str) -> str:
    """Convert comma-separated tags to a title."""
    words = [t.strip() for t in tags.split(",") if t.strip()]
    if words:
        return _capitalize(" ".join(words[:4]))
    return "Untitled"


def _capitalize(text: str) -> str:
    """Capitalize first letter, preserve rest."""
    if not text:
        return "Untitled"
    text = text.strip()
    return text[0].upper() + text[1:] if len(text) > 1 else text.upper()


def _fallback(item: dict) -> str:
    """Last resort title."""
    source = item.get("source", "Unknown")
    item_id = item.get("id", "?")
    return f"{source} clip {item_id}"


# Clean title for display (max 80 chars, no weird chars)
def clean_title(title: str, max_len: int = 80) -> str:
    """Trim and clean a title for display."""
    # Remove excessive whitespace
    title = re.sub(r"\s+", " ", title).strip()
    # Remove leading/trailing dashes
    title = title.strip("- ")
    # Truncate
    if len(title) > max_len:
        title = title[:max_len-3].rstrip() + "..."
    # Ensure first char is capitalized
    if title and title[0].islower():
        title = title[0].upper() + title[1:]
    return title
