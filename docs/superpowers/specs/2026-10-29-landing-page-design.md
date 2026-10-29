# sepia landing page: design

Date: 2026-10-29. Status: approved.

## Purpose

Say what sepia does, show a real run, and lead to `uv tool install sepia-cli`. The page
belongs to the same family as the landing pages of proofpath, spiyweb and reasonhound:
one colour theme, an animal, public-domain engravings, pencil-drawn UI, the same section
skeleton and a "Same family" footer. Like them, it never passes an example off as a real
result: every picture in the demo is real sepia output and every number comes from the
README.

## Look

- **Concept:** a naturalist's plate in ink. Warm pink-lilac paper, plum ink, an orchid
  pen. Light theme only, like the family; dark comes from orchid "fields" behind the
  rules, the numbers and the footer.
- **Animal:** the cuttlefish. sepia is the cuttlefish genus; the animal releases ink and
  paints patterns across its skin, which is what the tool does to a terminal.
- **Art:** public-domain cephalopod plates (Vérany 1851 for the hero), converted to
  characters at build time with sepia's own algorithm instead of the family's halftone
  dither. Every plate is credited from `images.manifest.json`.
- **Type:** Fraunces (display), Inter (body), IBM Plex Mono (labels, code, terminal),
  Kalam for the handwritten margin notes (each sibling has its own pen).
- **Colour:** tokens in `site/src/styles/tokens.css`, with the contrast ratio of each
  text pair written next to it. Text pairs meet WCAG AA.

## Effects: the family's logic, sepia's own effects

| Family | sepia |
| --- | --- |
| spiyweb: a live orb web in the hero, a click drops an energy pulse | A live ASCII cuttlefish. The pointer sends out ripples (a port of `ripple.py`), a click releases ink that packs the ring into dense glyphs, and a "passing cloud" of colour sweeps the skin now and then. Pause button; stops off-screen. |
| Halftone dither plates | Inkprint plates: characters chosen by sepia's ramp and Bayer dither |
| Halftone "develop" reveal | Characters decode from random glyphs to the final ones |
| Hover cross-fade to a second tone | A local ripple on hover (hover-capable pointers only) |
| Terminal replay with margin notes | Two windows: the prompt window types the request, the viewer paints the picture row by row |
| spiyweb's Trace (interactive graph) | Style lab: the same picture in `ink`/`fill` × `classic`/`symbols` |

Every animation is gated on `html.js` and `prefers-reduced-motion`. Reduced motion shows
the finished frame. Without JS the plates are plain `<pre>` text.

## Page

1. Nav (sticky, paper).
2. Hero: kicker with the version, "Describe it. Watch it ink.", lede, install box
   (uv, pipx, pip), the live cuttlefish and its credit.
3. `#watch` "A picture, as it surfaces.": the two-window replay of `waterfall` then
   `/add mountains`, generated with `scripts/spike.py --chain "waterfall" "mountains"`.
4. `#ink` "Describe. Direct. Paint. Ink.": four chapters with plates and ledgers.
5. `#styles` "Ink or fill. Letters or symbols.": the style lab and the two ramps.
6. `#rules` "Six things it will never do." (field).
7. `#measured` "Measured, not claimed." (field): only numbers the README states.
8. `#limits` "Where the ink runs out."
9. `#cli` "Two windows, one command.": commands, flags, the local extra, settings.
10. Footer (field): links, "Same family", engraving credits.

Also `404.astro` in sepia's voice, `social.astro` (the 1280×640 card in the family's
template: name, headline, a handwritten line, a mono footer line, the plate fading into
the paper on the right) and `robots.txt.ts`.

## Build

- Astro 7, static output, no UI framework, TypeScript strict, Prettier. Lives in `site/`
  of this repo; Vercel builds it with `site` as the project root, at
  https://sepia-cli.vercel.app.
- Shared family files (`stroke-draw.ts`, `run-notes.ts`, `nav.ts`, `sketch/*`,
  `lib/base.ts`, `lib/seo.ts`, `lib/mark.ts`) are copied from spiyweb's site and recoloured.
- `site/src/lib/ramps.ts` holds the constants of `src/sepia/ascii_art.py`.
  `site/scripts/ink.mjs` turns the plates and the demo pictures into cell data
  (`src/data/plates.generated.ts`): characters for the static text, densities and colours
  for the canvas. The demo conversion follows the Python algorithm step by step.
- Generated data and resized demo sources are committed; downloaded engravings are cached
  in `site/.cache/` and ignored.

## Verification

- `npm run check`, `npm run build` and `npm run format:check` in `site/` are clean.
- The characters `ink.mjs` produces for the demo picture match `sepia.ascii_art` for the
  same grid in at least 99% of cells.
- Lighthouse: 100 for accessibility, best practices and SEO. No horizontal scroll at
  390 px. No console errors. Reduced motion and no-JS both render a finished page.
