# ClipVault — Free Stock Media Search Engine
## Product Plan v2 · July 2026

---

## 1. PRODUCT OVERVIEW

A search engine for free stock video + sound effects. One search queries Pexels, Pixabay, and Freesound simultaneously. Clean, fast, no account needed.

**Core promise:** "Find the perfect clip in seconds, not hours."

---

## 2. PRICING

| Tier | Price | Searches | Features |
|---|---|---|---|
| **Free** | €0 | 10/month | Search all sources, preview, download |
| **Pro** | €10.99/month | Unlimited | Everything free has + search history + collections |

- Payment: Stripe (future phase — SKIPPED for now)
- Free tier requires no account
- Counter resets on the 1st of each month

---

## 3. SEARCH RESULT — WHAT EVERY CARD SHOWS

Each result card must include:

| Field | Source | Example |
|---|---|---|
| **Title** | Generated from tags/keywords | "Aerial drone shot of mountain range at sunset" |
| **Preview** | Inline video player (3-5 sec autoplay on hover) | MP4 thumbnail that plays on mouseover |
| **Source badge** | Colored pill | 🟣 Pexels / 🟢 Pixabay / 🟠 Freesound |
| **Duration** | MM:SS | 0:24 |
| **Resolution** | W×H | 1920×1080 |
| **Author** | Username | by john_doe |
| **Download** | Button | ⬇ Download |
| **Variants badge** | Only if duplicates exist | 🔗 3 variants |

### Title Generation Rules
- If API provides a description/title → use it
- If only tags → join top 3 tags into a sentence: "Sunset, ocean, drone" → "Sunset ocean drone footage"
- Always capitalize first letter
- Max 80 characters

---

## 4. DUPLICATE HANDLING — GROUP, DON'T HIDE

Same video often appears on multiple sources (Pexels, Pixabay). Different sources = different encoding quality, compression, watermarks. The user should see all variants and pick the best.

### How it works:

1. **Detect duplicates** across sources using:
   - Duration match (±0.5 sec tolerance)
   - Resolution match (must be same W×H)
   
2. **Group them** — don't hide. The primary card shows:
   ```
   ┌──────────────────────────────────┐
   │  [THUMBNAIL / PREVIEW]           │
   │                                  │
   │  🔗 3 variants available         │ ← badge on card
   │  Aerial mountain drone footage   │
   │  🟣 Pexels · 0:24 · 1920×1080   │
   │  [▶ Preview]  [⬇ Download]      │
   └──────────────────────────────────┘
   ```

3. **Click the badge or card** → expands to show all variants:
   ```
   ┌──────────────────────────────────┐
   │  Aerial mountain drone footage   │
   │                                  │
   │  ┌─ Variant 1 ─────────────────┐ │
   │  │ 🟣 Pexels · 68MB · 24fps    │ │
   │  │ [▶ Preview] [⬇ Download]   │ │
   │  └─────────────────────────────┘ │
   │  ┌─ Variant 2 ─────────────────┐ │
   │  │ 🟢 Pixabay · 42MB · 30fps   │ │
   │  │ [▶ Preview] [⬇ Download]   │ │
   │  └─────────────────────────────┘ │
   │  ┌─ Variant 3 ─────────────────┐ │
   │  │ 🟢 Pixabay (re-upload) · 55MB│ │
   │  │ [▶ Preview] [⬇ Download]   │ │
   │  └─────────────────────────────┘ │
   └──────────────────────────────────┘
   ```

4. **Default selection**: The highest-resolution, largest-file variant is highlighted as "Best quality"

5. **Single (no duplicates)**: No badge, just the normal card

---

## 5. PREVIEW PLAYER

- **Hover**: 3-second silent autoplay loop on mouseover
- **Click**: Opens full preview in a lightbox modal with full video player
- **Lightbox**: Source link, author credit, download button
- **Performance**: Lazy-load thumbnails, only load video on hover
- **Sound effects**: Audio waveform visualization instead of video, click-to-play preview

---

## 6. PAGES NEEDED

### 6.1 Homepage (`/`)
- Search bar (hero-style, centered)
- Tab toggle: 🎥 Videos | 🔊 Sound Effects
- "Searches remaining: X/10" badge (when below 5)
- Source status dots: 🟢 Pexels 🟢 Pixabay 🔴 Freesound

### 6.2 Search Results (same page, dynamic)
- Sticky search bar at top
- Results grid (3 columns desktop, 2 tablet, 1 mobile)
- Filter bar: source, duration, resolution
- Variant groups collapsed by default, expandable

### 6.3 Pricing Page (`/pricing`) — SIMPLE, NO STRIPE YET
- Free tier explained
- Pro tier "Coming soon" with email waitlist
- No payment integration yet

---

## 7. TECH STACK

| Layer | Choice | Why |
|---|---|---|
| Frontend | HTML/CSS/JS (vanilla) | No framework overhead, fast to build |
| Backend | Python Flask | Already running |
| Search tracking | localStorage + IP hash in memory | No database needed yet |
| Hosting | Local for now | `python app.py` |

*No database, no auth, no Stripe — keeps it simple for v1.*

---

## 8. FREE TIER TRACKING

- Store in browser localStorage: `{searches_used: 3, month: "2026-07"}`
- Also track by IP hash server-side (cross-browser, harder to cheat)
- On each search: check both, use the higher count
- Reset on 1st of month
- Badge below search bar: "5 of 10 free searches used this month"

---

## 9. FILE STRUCTURE (simplified — no auth/stripe)

```
clipvault/
├── app.py                  ← Flask backend + API aggregators
├── config.json             ← API keys
├── requirements.txt
├── dedup.py                ← Duplicate detection + grouping
├── titles.py               ← Title generation
├── templates/
│   ├── index.html          ← Homepage + search results (all in one)
│   └── pricing.html        ← Simple pricing page
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── search.js       ← Search + results rendering
│       ├── player.js       ← Hover preview + lightbox
│       └── tracker.js      ← Free tier usage tracking
├── downloads/              ← Saved files
└── PLAN.md                 ← This document
```

---

## 10. BUILD ORDER

| Phase | What | Time |
|---|---|---|
| **1** | Title generation from tags | 30 min |
| **2** | Dedup detection + variant grouping | 1 hour |
| **3** | Hover preview player (video + audio) | 1.5 hours |
| **4** | Variant expansion UI (badge → dropdown) | 1 hour |
| **5** | Free tier tracker (10/month) | 1 hour |
| **6** | Filters (source, duration, resolution) | 1 hour |
| **7** | Pricing page + search counter badge | 30 min |
| **8** | Polish, keyboard shortcuts, dark mode | 1 hour |

**Total: ~7.5 hours**

---

## 11. EXAMPLE: SEARCH "MOUNTAIN DRONE"

### Before grouping (raw API results):
| # | Source | Duration | Resolution |
|---|---|---|---|
| 1 | Pexels | 24s | 1920×1080 |
| 2 | Pixabay | 24s | 1920×1080 | ← duplicate of #1
| 3 | Pexels | 15s | 3840×2160 |
| 4 | Pixabay | 15s | 3840×2160 | ← duplicate of #3
| 5 | Pixabay | 15s | 3840×2160 | ← duplicate of #3 (re-upload)
| 6 | Pexels | 8s | 1920×1080 |

### After grouping (what user sees):
| Card | Variants | Details |
|---|---|---|
| 🔗 2 variants | Pexels + Pixabay | 24s · 1920×1080 · "Mountain drone aerial" |
| 🔗 3 variants | Pexels + Pixabay ×2 | 15s · 3840×2160 · "Snow peak drone flyover" |
| — | Pexels only | 8s · 1920×1080 · "Forest trail drone shot" |

User sees **3 cards instead of 6**, clicks badge to compare quality, picks the best file.

---

## 12. SOURCE COLORS

| Source | Color | Hex |
|---|---|---|
| Pexels | Purple | `#6c5ce7` |
| Pixabay | Green | `#00d68f` |
| Freesound | Orange | `#ff9f43` |
