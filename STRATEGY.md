# ClipVault — Product Strategy & Differentiation

## The Core Problem

Every stock site is a search box + grid of thumbnails. Pexels, Pixabay, Storyblocks — all identical. Editors don't need "yet another search box." They need a tool that fits their actual workflow: they have a script, they need clips for it.

## The Killer Feature: Script → Clips

### How it works
1. User pastes their ad script (or uploads .txt)
2. AI parses the script into scenes/lines (5-10 seconds each)
3. For each line, it runs keyword extraction + searches all sources
4. Returns a **storyboard view**: script line on the left, suggested clip on the right
5. User can:
   - Accept all suggestions ("Fill storyboard")
   - Swap individual clips (click → see alternatives)
   - Download all as a bundle
   - Export to Premiere/DaVinci as markers/timeline

### Why this converts
- The first time an editor pastes a script and sees it filled with clips in 5 seconds — they're sold
- Free tier: 3 script-to-clip generations/month
- Pro: unlimited + AI scene detection + batch export

### Technical implementation
- Parse script: split by line breaks, detect timecodes, detect speaker labels
- Extract keywords per line using NLP (simple TF-IDF or keyword extraction)
- Search each line's keywords through existing pipeline
- Return structured results: `{script: [{line, keywords, clips: [...]}]}`
- Frontend: split-panel view (script on left, clip previews on right)

---

## Design Philosophy — "Editor's Workbench"

### What NOT to do
- ✗ Blue/purple gradient (every SaaS in 2024-2026)
- ✗ Cards in a grid (Pexels, Pixabay, every competitor)
- ✗ "Free stock footage" as hero text (boring, commodity)

### What TO do
- ✓ **Warm, editorial feel** — dark amber/orange accents on deep charcoal (like a color-graded editing suite)
- ✓ **Timeline-inspired layout** — horizontal scrub, thumbnails in sequence
- ✓ **Single-panel workbench** — no tab-hopping, everything in one view
- ✓ **Typography that feels editorial** — serif for headings, mono for metadata
- ✓ **Sound design** — subtle hover sounds, download confirmation (brand trust cue)

### Visual identity
```
Background: #0d0c0a (warm charcoal, not cold black)
Surface: #1a1814 (dark wood/slate)
Accent: #f0a030 (amber/gold — warmth, premium)
Secondary: #c4a86a (muted gold)
Success: #8fb85c (olive green)
Text: #e8e4dc (warm white)
Muted: #8a8578 (warm grey)
Danger: #d45a3a (terracotta red)
```

### Homepage layout
```
┌─────────────────────────────────────────┐
│  ClipVault — Your script, filmed.       │  (serif, bold)
│  Paste a script, get matched clips.     │  (subtitle)
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ [Paste your ad script here...]  │    │  (the hero IS the tool)
│  │                                 │    │
│  │ SCENE 1: Drone over mountains   │    │
│  │ SCENE 2: Close-up product shot  │    │
│  │ ...                             │    │
│  └─────────────────────────────────┘    │
│  [Generate Clips]  or  [Browse Library] │
│                                         │
│  "1,200+ editors found clips for their  │
│   ads in under 60 seconds last week"     │  (social proof)
└─────────────────────────────────────────┘
```

---

## Trust Architecture

### 1. Transparent sourcing
Every clip shows:
- Source logo + link to original
- License type (CC0, CC-BY, Pixabay License)
- Resolution/size verified
- "No attribution" badge when applicable

### 2. Social proof layer
- Live counter: "X editors searching right now"
- Testimonials from editor communities (Reddit r/editors, r/videoediting)
- "As seen in" — logos of editing tools/communities
- Usage stats: "247K clips downloaded, 12K scripts processed"

### 3. Security trust
- No credit card for free tier
- SSL certificate + "Your data stays on your machine" messaging
- GDPR compliance badge
- "Used by editors at [agency names]" if possible

### 4. Quality trust
- "Every clip verified by our team" badge
- Resolution guarantee (no SD upscales)
- "Audio optimized for editing" — your existing ffmpeg pipeline
- "No watermarks, ever"

---

## Conversion Funnel

### Tier structure
| Feature | Free | Pro (€9.99/mo) |
|---|---|---|
| Searches | 10/mo | Unlimited |
| Script-to-clips | 3/mo | Unlimited |
| Sources | Pixabay + Freesound | All 5+ sources |
| Quality | Up to 1080p | Up to 4K |
| Audio optimization | ✗ | ✓ |
| Batch download | ✗ | ✓ all in one zip |
| Export to Premiere | ✗ | ✓ (EDL/XML markers) |
| Watermark | None | None |

### The conversion trigger
The free tier is generous enough to be useful, but the workflow speed-up on Pro is undeniable. The script-to-clips feature is the hook — 3 free uses, then "You've used your 3 script generations this month. Go Pro for unlimited."

### Pricing psychology
- €9.99, not €10.99 — under €10 feels dramatically cheaper
- Annual: €7.99/mo (€95.88/year) — "Save 20%"
- No free trial of Pro — the free tier IS the trial
- Cancel anytime, no questions (reduces friction)

---

## Full Feature Roadmap

### Phase 1: Core differentiation (now)
- [x] Multi-source search with keyword expansion
- [x] Audio optimization pipeline
- [ ] Script-to-clips (parsing + auto-search)
- [ ] Storyboard UI (split-panel)
- [ ] Warm amber design system

### Phase 2: Trust + conversion
- [ ] Stripe integration
- [ ] User accounts with tier enforcement
- [ ] Live stats + testimonials
- [ ] Transparent licensing per clip
- [ ] "Pro" badge on locked features (not hidden)

### Phase 3: Pro workflow
- [ ] Batch download (all storyboard clips as ZIP)
- [ ] Premiere/DaVinci export (EDL markers or XML)
- [ ] Collections/folders
- [ ] Search history + "recently used"

### Phase 4: Growth
- [ ] Affiliate program (editors earn % of referrals)
- [ ] YouTube integration (search while editing)
- [ ] Team/agency accounts
- [ ] API for other tools to use ClipVault

---

## What Makes This Convert (Summary)

1. **The script-to-clips feature IS the demo** — first use sells itself
2. **Free tier is the trial** — no credit card, no pressure, just a wall they hit naturally
3. **Editor-first design** — not another generic SaaS, but a tool that feels like it was built by an editor
4. **Trust built into every pixel** — transparent licensing, verified sources, social proof, no dark patterns
5. **Warm, premium aesthetic** — the amber/charcoal palette alone sets it apart from every blue/purple competitor

---

## Immediate Next Steps

1. Build script parsing endpoint (`/api/parse-script`) — splits into lines, extracts keywords
2. Build storyboard view — split panel with script left, clips right
3. Apply warm amber design system to existing pages
4. Add trust badges + live stats (even if simulated initially)
5. Once script-to-clips works end-to-end, build Stripe + tier gating
