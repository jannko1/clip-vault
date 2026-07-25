"""
Duplicate detection and variant grouping for video/audio search results.
Groups identical clips from different sources so users can compare and pick the best.
"""
from collections import defaultdict


def group_duplicates(results: list) -> list:
    """
    Takes a flat list of result dicts and returns a list of groups.
    
    Each group has:
      - primary: the "best" result (highest quality)
      - variants: list of all results for this clip (including primary)
      - has_variants: True if 2+ results are the same clip
    
    Groups remain in the same order as the first occurrence.
    """
    if not results:
        return []
    
    # Step 1: Build clusters of duplicates
    clusters = _cluster_by_fingerprint(results)
    
    # Step 2: For each cluster, pick the primary and build the group
    # Maintain original order by tracking first occurrence
    order = []
    seen_cluster_ids = set()
    
    for r in results:
        fid = _fingerprint(r)
        cluster_id = _cluster_id(fid, clusters)
        
        if cluster_id in seen_cluster_ids:
            continue
        
        seen_cluster_ids.add(cluster_id)
        group_results = clusters[cluster_id]
        
        # Pick best as primary
        primary = _pick_best(group_results)
        
        order.append({
            "primary": primary,
            "variants": group_results,
            "has_variants": len(group_results) > 1,
            "variant_count": len(group_results),
        })
    
    return order


def _fingerprint(item: dict) -> tuple:
    """
    Create a fingerprint for dedup matching.
    Returns (duration_rounded, width, height) as a comparable tuple.
    """
    duration = float(item.get("duration", 0) or 0)
    width = int(item.get("width", 0) or 0)
    height = int(item.get("height", 0) or 0)
    
    # Round duration to nearest 0.5s to catch minor differences
    dur_rounded = round(duration * 2) / 2
    
    return (dur_rounded, width, height)


def _cluster_by_fingerprint(results: list) -> dict:
    """
    Group results by fingerprint with tolerance matching.
    Returns {cluster_id: [result1, result2, ...]}
    """
    clusters = {}  # fingerprint_tuple -> [results]
    fp_to_cluster = {}  # fingerprint_tuple -> canonical fingerprint
    
    for r in results:
        fp = _fingerprint(r)
        
        # Check if this fingerprint matches any existing cluster
        matched = False
        for existing_fp in list(clusters.keys()):
            if _fingerprints_match(fp, existing_fp):
                clusters[existing_fp].append(r)
                fp_to_cluster[fp] = existing_fp
                matched = True
                break
        
        if not matched:
            clusters[fp] = [r]
            fp_to_cluster[fp] = fp
    
    return clusters


def _fingerprints_match(fp1: tuple, fp2: tuple) -> bool:
    """
    Check if two fingerprints represent the same clip.
    
    Match criteria:
    - Duration within ±0.5 seconds
    - Same width AND height (resolution must match exactly)
    """
    dur1, w1, h1 = fp1
    dur2, w2, h2 = fp2
    
    # Duration within 1 second tolerance
    if abs(dur1 - dur2) > 1.0:
        return False
    
    # Resolution must match
    if w1 != w2 or h1 != h2:
        return False
    
    return True


def _cluster_id(fp: tuple, clusters: dict) -> tuple:
    """Find which cluster a fingerprint belongs to."""
    for existing_fp in clusters:
        if _fingerprints_match(fp, existing_fp):
            return existing_fp
    return fp


def _pick_best(results: list) -> dict:
    """
    Pick the best variant as the primary display card.
    
    Priority:
    1. Highest resolution (width × height)
    2. Pexels > Pixabay > Freesound (Pexels usually has better encoding)
    3. If same source, first one wins
    """
    if len(results) == 1:
        return results[0]
    
    source_rank = {"Pexels": 0, "Pixabay": 1, "Freesound": 2}
    
    def sort_key(r):
        res = (r.get("width", 0) or 0) * (r.get("height", 0) or 0)
        src = source_rank.get(r.get("source", ""), 99)
        # Negative resolution so higher = better, positive source so lower = better
        return (-res, src)
    
    return sorted(results, key=sort_key)[0]
