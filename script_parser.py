"""
Script parser — splits ad scripts into scenes, extracts keywords, finds matching clips.
Used by ClipVault's "Script → Clips" feature.
"""
import re
from collections import Counter

# Common English stopwords to filter out when extracting keywords
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "you", "your",
    "yours", "he", "she", "it", "its", "we", "our", "they", "them",
    "their", "this", "that", "these", "those", "what", "which", "who",
    "whom", "how", "when", "where", "why", "not", "no", "so", "if",
    "then", "than", "too", "very", "just", "about", "up", "out",
    "there", "here", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "only", "own", "same", "into",
    "over", "under", "again", "once", "now", "also", "get", "got",
    "make", "made", "like", "know", "see", "look", "want", "need",
    "come", "take", "give", "use", "find", "tell", "ask", "try",
    "leave", "keep", "let", "seem", "still", "well", "way", "even",
    "new", "good", "any", "thing", "one", "two", "time", "day",
    "man", "woman", "people", "think", "say", "go", "really",
    "much", "back", "down", "right", "left", "through", "around",
    "never", "always", "ever", "going", "yeah", "yea", "oh", "uh",
    "um", "er", "ah", "hey", "ok", "okay", "alright", "yes", "nah",
    "his", "her", "him", "my", "me", "i", "our", "us", "myself",
    "yourself", "himself", "herself", "itself", "ourselves",
    "themselves", "am", "doesn", "don", "aren", "isn", "didn",
    "won", "wasn", "weren", "haven", "hasn", "hadn",
}

# Scene transition markers — lines that indicate a new scene
SCENE_MARKERS = [
    "SCENE", "CUT TO", "FADE IN", "FADE OUT", "DISSOLVE",
    "INT.", "EXT.", "INT ", "EXT ",
    "SCENE:", "SHOT:", "TAKE:",
]

# Visual keywords that map well to stock footage searches
# Weight 3 = critical shot type (must include), 2 = important descriptor, 1 = nice-to-have
VISUAL_WEIGHTS = {
    # Shot types — highest priority
    "drone": 4, "aerial": 4, "closeup": 4, "close-up": 4, "macro": 4,
    "wide": 3, "panoramic": 3, "establishing": 3, "pov": 3,
    "tracking": 3, "dolly": 3, "panning": 3, "handheld": 2,
    "overhead": 3, "top-down": 3, "bird": 3, "birds-eye": 3,
    # Lighting
    "golden": 3, "sunrise": 3, "sunset": 3, "dusk": 3, "dawn": 3,
    "backlit": 2, "silhouette": 3, "shadow": 2, "moody": 2,
    "dark": 2, "bright": 1, "natural": 1, "studio": 2,
    # Mood & color
    "warm": 2, "cold": 2, "cinematic": 3, "dramatic": 2,
    "peaceful": 1, "serene": 1, "tense": 1, "energetic": 1,
    "blue": 1, "gold": 2, "amber": 2, "teal": 1, "orange": 1,
    # Movement
    "slow": 3, "fast": 2, "static": 2, "timelapse": 3,
    "slow-motion": 3, "speed": 1, "motion": 1, "flying": 2,
    "moving": 1, "gliding": 2, "sweeping": 2, "rising": 1,
    # Environment
    "mountains": 2, "forest": 2, "ocean": 2, "beach": 2, "desert": 2,
    "city": 2, "urban": 2, "rural": 2, "nature": 2, "landscape": 2,
    "backyard": 2, "garden": 2, "farm": 2, "field": 2, "sky": 2,
    "indoor": 1, "outdoor": 1, "office": 1, "home": 1, "kitchen": 1,
    "road": 1, "street": 1, "house": 1, "building": 1, "room": 1,
    # Subjects
    "product": 3, "person": 2, "people": 2, "family": 2, "child": 2,
    "chicken": 3, "animal": 2, "dog": 2, "cat": 2, "bird": 3,
    "hand": 2, "face": 2, "eyes": 2, "smile": 2, "crowd": 2,
    "car": 2, "door": 2, "water": 2, "fire": 2, "food": 2,
    # Generic descriptors — lower weight
    "shot": 1, "footage": 1, "view": 1, "angle": 1, "scene": 1,
    "background": 1, "clip": 1, "video": 1, "stock": 1,
}

# Compound phrases that should stay together as one search term
COMPOUND_TERMS = [
    "golden hour", "slow motion", "birds eye", "top down",
    "close up", "high angle", "low angle", "depth of field",
    "shallow focus", "deep focus", "wide angle",
]


def parse_script(text: str) -> list[dict]:
    """
    Parse a script into scenes with extracted keywords.
    
    Returns: [{line, keywords, search_query, is_scene_break}, ...]
    """
    lines = _split_into_lines(text)
    scenes = []
    
    for line in lines:
        if not line.strip():
            continue
        
        is_break = _is_scene_break(line)
        keywords = _extract_keywords(line)
        search_query = _build_search_query(keywords, line)
        
        scenes.append({
            "line": line.strip(),
            "keywords": keywords,
            "search_query": search_query,
            "is_scene_break": is_break,
        })
    
    return scenes


def _split_into_lines(text: str) -> list[str]:
    """Split text into logical lines, handling various script formats."""
    # Remove excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text.strip())
    
    lines = []
    for raw_line in text.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        
        # Handle timecodes: "0:00-0:05 Something happens"
        timecode_match = re.match(r'^[\d:.\-]+\s+(.+)', line)
        if timecode_match:
            line = timecode_match.group(1)
        
        # Handle speaker labels: "SPEAKER: text"
        speaker_match = re.match(r'^[A-Z][A-Z\s]+:\s*(.+)', line)
        if speaker_match:
            line = speaker_match.group(1)
        
        # Handle numbered scenes: "1. Something" or "1) Something"
        numbered = re.match(r'^[\d]+[.)]\s*(.+)', line)
        if numbered:
            line = numbered.group(1)
        
        lines.append(line)
    
    return lines


def _is_scene_break(line: str) -> bool:
    """Check if this line is a scene transition marker."""
    upper = line.upper().strip()
    for marker in SCENE_MARKERS:
        if upper.startswith(marker):
            return True
    # Also treat fully uppercase short lines as transitions
    if upper == line and len(line) < 30 and not line.endswith('.'):
        if any(word.isalpha() and len(word) > 2 for word in line.split()):
            return True
    return False


def _extract_keywords(line: str) -> list[str]:
    """
    Extract visual keywords from an editor's description.
    Detects compound phrases (golden hour), weights visual terms higher,
    and always includes shot-type keywords (drone, aerial, closeup) first.
    Returns top 6 keywords sorted by visual relevance.
    """
    lower = line.lower()
    
    # Step 1: Detect compound phrases and replace with hyphenated versions
    for phrase in COMPOUND_TERMS:
        if phrase in lower:
            lower = lower.replace(phrase, phrase.replace(" ", "-"))
    
    # Tokenize
    words = re.findall(r'[a-zA-Z][a-zA-Z-]*', lower)
    
    # Filter and weight
    candidates = []
    for w in words:
        clean = w.replace("-", " ")
        base = w.split("-")[0]
        
        if len(base) < 2:
            continue
        if base in STOPWORDS:
            continue
        
        weight = VISUAL_WEIGHTS.get(base, VISUAL_WEIGHTS.get(clean, 1))
        candidates.extend([clean] * weight)
    
    counter = Counter(candidates)
    
    # Shot types (weight >= 3) always come first
    shot_types = [w for w, c in counter.items() if VISUAL_WEIGHTS.get(w, 0) >= 3]
    others = [w for w, _ in counter.most_common(12) if w not in shot_types]
    
    top = shot_types[:2] + others[:4]
    
    if not top and words:
        meaningful = [w for w in words if len(w) > 2 and w not in STOPWORDS]
        top = meaningful[:4] if meaningful else words[:2]
    
    return [w for w in top if w]


def _build_search_query(keywords: list[str], line: str) -> str:
    """
    Build a search query from keywords.
    Uses the keywords directly or falls back to the full line.
    """
    if keywords:
        return " ".join(keywords)
    # Fallback: use the line itself, stripped of punctuation
    clean = re.sub(r'[^\w\s]', '', line)
    words = [w for w in clean.split() if len(w) > 2 and w.lower() not in STOPWORDS]
    return " ".join(words[:4]) if words else clean[:60]


def format_for_storyboard(scenes: list[dict]) -> str:
    """
    Format parsed scenes as a readable summary for display.
    """
    output = []
    for i, scene in enumerate(scenes):
        marker = "🎬" if scene["is_scene_break"] else "  "
        kw = ", ".join(scene["keywords"]) if scene["keywords"] else "(no keywords)"
        output.append(f"{marker} [{i+1}] {scene['line'][:60]}")
        output.append(f"     🔍 searching: {scene['search_query']}")
    return "\n".join(output)
