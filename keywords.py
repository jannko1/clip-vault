"""
Keyword expander — generates related search terms to find more content.
V2: Smarter expansion. Exact matches first, conservative synonyms, typo correction.
"""
import re

# ── Typo correction for common misspellings ──
TYPO_FIXES = {
    "coffe": "coffee",
    "recieve": "receive",
    "teh": "the",
    "thier": "their",
    "definately": "definitely",
    "seperate": "separate",
    "occured": "occurred",
    "untill": "until",
    "wich": "which",
    "beleive": "believe",
    "acheive": "achieve",
    "begining": "beginning",
    "calender": "calendar",
    "enviroment": "environment",
    "goverment": "government",
    "occassion": "occasion",
    "succesful": "successful",
    "tommorow": "tomorrow",
    "tommorrow": "tomorrow",
    "untill": "until",
    "wich": "which",
}

# ── Filler words to ignore when generating focused queries ──
FILLER_WORDS = {
    "the", "a", "an", "for", "of", "in", "on", "at", "to", "with",
    "and", "or", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall",
    "this", "that", "these", "those", "it", "its",
    "shot", "footage", "video", "clip", "stock", "free",
    "broll", "b-roll", "scene", "view",
}

# ── Conservative synonym groups — only for truly interchangeable terms ──
SYNONYMS = {
    "sunlight": ["sun", "sunshine", "sun rays"],
    "sunrise": ["dawn", "sunup"],
    "sunset": ["dusk", "sundown"],
    "forest": ["woods", "woodland"],
    "mountain": ["mountains", "peak", "summit"],
    "ocean": ["sea", "seaside"],
    "city": ["urban", "downtown"],
    "rain": ["rainy", "rainfall", "raining"],
    "storm": ["thunderstorm", "lightning"],
    "snow": ["snowy", "snowfall", "winter"],
    "drone": ["aerial"],
    "closeup": ["close-up", "close up", "macro"],
    "office": ["workspace", "workplace"],
    "desk": ["table", "workstation"],
    "lamp": ["light", "lighting"],
    "window": ["windows", "windowpane"],
    "coffee": ["cafe", "espresso", "latte"],
    "car": ["vehicle", "driving"],
    "dog": ["puppy", "canine"],
    "cat": ["kitten", "feline"],
    "baby": ["infant", "newborn", "toddler"],
    "couple": ["couples", "pair", "together"],
    "night": ["nighttime", "nocturnal"],
    "dark": ["darkness", "dim"],
    "fire": ["flame", "flames", "burning"],
    "water": ["river", "lake", "stream", "waterfall"],
    "sky": ["skies", "clouds", "heavens"],
    "slow": ["slow motion", "gentle"],
    "fast": ["quick", "speed", "rapid"],
    "aerial": ["drone", "bird eye", "overhead", "flyover"],
    "food": ["cooking", "meal", "kitchen"],
    "people": ["crowd", "person", "group"],
    "business": ["corporate", "meeting", "work"],
    "nature": ["outdoor", "landscape", "scenic"],
    "technology": ["tech", "digital", "computer"],
    "flower": ["bloom", "blossom", "garden"],
    "space": ["universe", "galaxy", "cosmos"],
    "dance": ["dancing", "movement"],
    "running": ["run", "jogging", "sprint"],
}


def correct_typos(query: str) -> str:
    """Fix common misspellings in search query."""
    words = query.split()
    fixed = [TYPO_FIXES.get(w.lower(), w) for w in words]
    return " ".join(fixed)


def expand_query(query: str, max_terms: int = 6) -> list[str]:
    """
    Smart query expansion that prioritizes relevance over coverage.
    
    Strategy:
    1. Search the EXACT query (highest priority)
    2. Search without filler words
    3. Search with 2-3 most important words combined
    4. Search important words individually
    5. Light synonym swaps only when needed
    
    Returns list of query strings, exact match first.
    """
    if not query.strip():
        return [query]
    
    # Typo fix
    query = correct_typos(query).strip()
    
    words = [w for w in re.findall(r"[a-zA-Z]+", query.lower())]
    if not words:
        return [query]
    
    # Separate content words from filler
    content_words = [w for w in words if w not in FILLER_WORDS and len(w) > 2]
    
    queries = []
    
    # 1. EXACT query — always first, highest priority
    queries.append(query)
    
    # 2. Content words only (drop fillers) — keeps core meaning
    if content_words and len(content_words) < len(words):
        focused = " ".join(content_words)
        if focused != query and focused not in queries:
            queries.append(focused)
    
    # 3. Top 2-3 content words — most specific search
    if len(content_words) >= 3:
        top3 = " ".join(content_words[:3])
        if top3 not in queries:
            queries.append(top3)
    if len(content_words) >= 2:
        top2 = " ".join(content_words[:2])
        if top2 not in queries:
            queries.append(top2)
    
    # 4. Individual important words (only words with 4+ chars)
    for w in content_words:
        if len(w) >= 4 and w not in queries and len(queries) < max_terms:
            queries.append(w)
    
    # 5. Conservative synonym swaps — only replace ONE word at a time
    #    and only with direct synonyms (not category expansions)
    if len(queries) < max_terms:
        for i, word in enumerate(content_words):
            if len(queries) >= max_terms:
                break
            syns = _get_synonyms(word)
            if not syns:
                continue
            # Use only the closest synonym, not the whole group
            for syn in syns[:2]:
                if syn.lower() == word.lower():
                    continue
                new_words = content_words.copy()
                new_words[i] = syn
                new_q = " ".join(new_words)
                if new_q not in queries and len(queries) < max_terms:
                    queries.append(new_q)
    
    # 6. If we have very few results, try broader search
    if len(queries) < max_terms and len(content_words) >= 2:
        broader = " ".join(content_words[1:])  # Drop first word
        if broader not in queries:
            queries.append(broader)
    
    return queries[:max_terms]


def _get_synonyms(word: str) -> list[str]:
    """Get direct synonyms for a word (no category expansion)."""
    w = word.lower()
    if w in SYNONYMS:
        return SYNONYMS[w]
    # Check if word is in any synonym group
    for key, syns in SYNONYMS.items():
        if w in syns:
            return [key] + [s for s in syns if s != w]
    return []
