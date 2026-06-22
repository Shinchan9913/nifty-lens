# Agent sprites + background

These power the walking characters and floor in the dashboard office
animation (`src/dashboard/src/components/PixelOffice.tsx`). FastAPI serves this
folder at `/agents/sprites/<file>` (see `src/api/main.py`).

## What's here
| file | agent / use | look |
|------|-------------|------|
| `strategist.png` | Strategist (lead) | blonde hero kid |
| `technical.png`  | Technical analyst | little robot |
| `risk.png`       | Risk analyst      | chibi knight |
| `research.png`   | Market researcher | detective w/ hat |
| `background.png` | office floor (680×440) | dark wood-plank tile |

A missing file silently falls back to the built-in procedural figure / floor —
nothing breaks.

## Art credit / license
Characters: **Ninja Adventure Asset Pack** by *pixel-boy & AAA* — **CC0 1.0**
(public domain, no attribution required). Cute chibi pixel art.
https://pixel-boy.itch.io/ninja-adventure-asset-pack

## Sprite format (already normalized)
Each character PNG is a **4-row × 4-frame** sheet of **16×16** cells:

```
        frame0 frame1 frame2 frame3
row 0:  down
row 1:  up
row 2:  left
row 3:  right
```

Matches the `WALK` config in PixelOffice.tsx
(`frameW/H:16, rows:{down:0,up:1,left:2,right:3}, frames:4, scale:1.25`).
The native Ninja Adventure sheets are transposed (direction in columns); they
were re-sliced into this row-per-direction layout at import.

## Note on resolution vs. cuteness
16px chibi art is intentionally rendered small here so it reads as crisp pixel
art rather than blocky upscaling. If you want **cute AND high-detail**
characters, that combo basically only exists in paid packs — e.g. LimeZu
"Modern Interiors" (the original ask). Drop a 32px+ top-down walk sheet in and
bump `frameW/frameH/scale` in PixelOffice.tsx to use it.

## Swapping characters
Pick any of the 25 Ninja Adventure characters (or another top-down pack),
re-slice transposing columns(direction)→rows and rows(frame)→columns, and save
over the file above.
