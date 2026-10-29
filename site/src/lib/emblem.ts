/* The sepia mark: a cuttlefish drawn the way the tool draws everything, in
   characters. The figure is Vérany's 1851 plate run through sepia's own code at
   18 x 15 cells (scripts/site_art.py), set in the bands from pink to violet on a
   plum tile, and four arms of characters leave its head, two to each side: each
   rises, turns over and falls straight, an upturned J.

   The characters are outlines of IBM Plex Mono (data/glyphs.generated.ts), so the
   mark is the same in the nav, in a browser tab and in a PNG. Used by
   components/Logo.astro and pages/favicon.svg.ts. */
import { glyphs, ADVANCE, UNITS_PER_EM } from '../data/glyphs.generated';
import { pickChar } from './ramps';

const FIGURE = [
    '     ?WO%OX',
    '     8@QWQQc',
    '    b@QW0QQW^',
    '   ,@Qb}}nO8O',
    '    QO|%O0(Qo',
    ' _+wQQ0|<%W%0o?!',
    `'"(QQw"_',_"!c!!\``,
    `^^wQWo!_,,!,+?("^`,
    `_"XQOf^^'''"^|i<^`,
    `!!wQ0o!,'\`<^+?f<!`,
    `_"fW8w^-\`'^^+f?<\``,
    `'^+bQbi''_"!af<"`,
    " __(OWX<'-|w}<!`",
    '  ,^?XWOaXw(<!`',
    '   `_!+wwn^"\'',
];
const COLS = Math.max(...FIGURE.map((l) => l.length));
// A cell is 0.6 of the font size wide and 1.2 tall (a terminal's 1:2).
const FONT = 3.2;
const CELL_W = (FONT * ADVANCE) / UNITS_PER_EM;
const LEAD = FONT * 1.2;
const left = 50 - (COLS * CELL_W) / 2;
// Set a little low, so the arms rising above the head leave the tile balanced.
const SHIFT = 4;
const top = 50 - (FIGURE.length * LEAD) / 2 + FONT * 0.9 + SHIFT;
const cellTop = top - FONT * 0.9;

type Pt = [number, number];
const span = (row: number): [number, number] => {
    const line = FIGURE[row] ?? '';
    const first = line.search(/\S/);
    return [left + first * CELL_W, left + line.trimEnd().length * CELL_W];
};
// A point on a run of cubic segments, t from 0 to 1 over all of them.
const bezier = (p: Pt[], t: number): Pt => {
    const segs = (p.length - 1) / 3;
    const k = Math.min(segs - 1, Math.floor(t * segs));
    const u = t * segs - k;
    const [p0, p1, p2, p3] = [p[3 * k]!, p[3 * k + 1]!, p[3 * k + 2]!, p[3 * k + 3]!];
    const m = 1 - u;
    return [0, 1].map(
        (i) => m ** 3 * p0[i]! + 3 * m * m * u * p1[i]! + 3 * m * u * u * p2[i]! + u ** 3 * p3[i]!,
    ) as Pt;
};
// An upturned J: up from the root, over in a half circle, straight down.
const K = 0.5523; // a quarter circle as one cubic
const crook = (xu: number, xd: number, root: number, turn: number, end: number): Pt[] => {
    const xc = (xu + xd) / 2;
    const r = (xu - xd) / 2;
    const third = (a: number, b: number): [number, number] => [
        a + (b - a) / 3,
        a + (2 * (b - a)) / 3,
    ];
    const [u1, u2] = third(root, turn);
    const [d1, d2] = third(turn, end);
    return [
        [xu, root],
        [xu, u1],
        [xu, u2],
        [xu, turn],
        [xu, turn - K * r],
        [xc + K * r, turn - r],
        [xc, turn - r],
        [xc - K * r, turn - r],
        [xd, turn - K * r],
        [xd, turn],
        [xd, d1],
        [xd, d2],
        [xd, end],
    ];
};

/** The arms' cells: thick strokes that thin toward the tip, each cell near one
    taking the ramp's glyph for how much of the stroke covers it, as the figure's
    cells do for the engraving. Computed once. */
const ARMS: { x: number; y: number; c: string }[] = (() => {
    const rootRow = (share: number): number => Math.round(share * (FIGURE.length - 1));
    // The two on a side nest, the inner one under the outer one's arc; the right
    // pair mirrors the left about the middle of the figure.
    const rows = FIGURE.map((_, r) => r).filter((r) => r >= 3 && r <= FIGURE.length - 4);
    const middle = rows.map(span).reduce((sum, [l, r]) => sum + (l + r) / 2, 0) / rows.length;
    const mirror = (pts: Pt[]): Pt[] => pts.map(([x, y]) => [2 * middle - x, y]);
    const outer = crook(30.5, 16.5, cellTop + (rootRow(0.22) + 0.6) * LEAD, 24 + SHIFT, 76 + SHIFT);
    const inner = crook(25, 21, cellTop + (rootRow(0.42) + 0.6) * LEAD, 31 + SHIFT, 70 + SHIFT);
    const curves = [outer, inner, mirror(outer), mirror(inner)];

    const occupied = new Set<string>();
    FIGURE.forEach((line, row) =>
        [...line].forEach((c, col) => {
            if (c !== ' ') occupied.add(`${col},${row}`);
        }),
    );
    const ROOT_HALF = 1.5; // half the stroke's width at the root, in tile units
    const TIP_HALF = 0.65;
    const strokes = curves.map((curve) => {
        const samples: { at: Pt; len: number }[] = [];
        let len = 0;
        let prev: Pt | null = null;
        for (let t = 0; t <= 1.0001; t += 0.001) {
            const at = bezier(curve, t);
            if (prev) len += Math.hypot(at[0] - prev[0], at[1] - prev[1]);
            samples.push({ at, len });
            prev = at;
        }
        return { samples, total: len };
    });
    const cells: { x: number; y: number; c: string }[] = [];
    for (let row = Math.floor(-cellTop / LEAD); row <= Math.ceil((100 - cellTop) / LEAD); row++) {
        for (let col = Math.floor(-left / CELL_W); col <= Math.ceil((100 - left) / CELL_W); col++) {
            if (occupied.has(`${col},${row}`)) continue;
            const cx = left + (col + 0.5) * CELL_W;
            const cy = cellTop + (row + 0.5) * LEAD;
            let share = 0;
            for (const { samples, total } of strokes) {
                for (const { at, len } of samples) {
                    const u = len / total;
                    const half = ROOT_HALF + (TIP_HALF - ROOT_HALF) * u;
                    // Cells are twice as tall as wide: measure in cell widths both ways.
                    const d = Math.hypot(cx - at[0], (cy - at[1]) * 0.55);
                    if (d >= half) continue;
                    share = Math.max(share, (1 - d / half) ** 0.3 * (1 - 0.38 * u));
                }
            }
            if (share < 0.06) continue;
            const c = pickChar(share, row, col, 'classic');
            if (c !== ' ') cells.push({ x: left + col * CELL_W, y: top + row * LEAD, c });
        }
    }
    return cells;
})();

const FIGURE_CELLS = FIGURE.flatMap((line, row) =>
    [...line].flatMap((c, col) =>
        c === ' ' ? [] : [{ x: left + col * CELL_W, y: top + row * LEAD, c }],
    ),
);

const n = (v: number): string => String(+v.toFixed(2));

type Rgb = [number, number, number];
type Stops = [number, Rgb][];
const INK: Stops = [
    [0, [255, 128, 200]],
    [0.5, [236, 92, 236]],
    [1, [178, 120, 255]],
];
const ARM: Stops = [
    [0, [255, 96, 176]],
    [1, [176, 112, 255]],
];
// On a light tile the characters are the plates' ink: deep pink to violet.
const INK_PAPER: Stops = [
    [0, [219, 39, 119]],
    [0.5, [192, 38, 211]],
    [1, [109, 40, 217]],
];
const ARM_PAPER: Stops = [
    [0, [190, 24, 93]],
    [1, [109, 40, 217]],
];

/** `night` is the plum tile of the favicon and the dark bands; `paper` a pale
    tile in the page's own tints, for light grounds such as the nav. */
export type EmblemTone = 'night' | 'paper';
/** The colour of a linear gradient from `a` to `b` at point `p`, as a hex string:
    each glyph is coloured where it stands, since a gradient on a reused glyph
    would restart at every copy. */
function along(
    stops: Stops,
    a: [number, number],
    b: [number, number],
    p: [number, number],
): string {
    const [dx, dy] = [b[0] - a[0], b[1] - a[1]];
    const t = Math.min(
        1,
        Math.max(0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)),
    );
    let i = 0;
    while (i < stops.length - 2 && t > stops[i + 1]![0]) i++;
    const [t0, c0] = stops[i]!;
    const [t1, c1] = stops[i + 1]!;
    const u = (t - t0) / (t1 - t0 || 1);
    return `#${c0
        .map((v, k) =>
            Math.round(v + (c1[k]! - v) * u)
                .toString(16)
                .padStart(2, '0'),
        )
        .join('')}`;
}

/** A glyph's outline at the mark's size: every coordinate scaled (the paths are
    absolute), so a copy can be placed by its use's x and y alone. */
const scaled = (d: string): string =>
    // A space before each number: a scaled value can round to 0 and lose the minus
    // sign that was all that parted it from the number before.
    d.replace(/-?\d*\.?\d+(?:e-?\d+)?/g, (v) => ` ${n((Number(v) * FONT) / UNITS_PER_EM)}`);

/** The mark as SVG markup. `id` keeps its glyphs apart from another copy on the
    same page; `attrs` are put on the <svg> element as they are. */
export function emblemSvg(
    id: string,
    attrs = '',
    tone: EmblemTone = 'night',
    /** Fatten the glyphs with a stroke of their own colour: for favicon sizes,
        where a thin character averages into the tile. */
    heavy = false,
): string {
    const paper = tone === 'paper';
    const used = new Set([...ARMS, ...FIGURE_CELLS].map((cell) => cell.c));
    const key = (c: string): string => `${id}-g${c.charCodeAt(0)}`;
    const defs = [...used]
        .filter((c) => glyphs[c])
        .map((c) => `<path id="${key(c)}" d="${scaled(glyphs[c]!)}"/>`)
        .join('');
    const uses = (
        cells: { x: number; y: number; c: string }[],
        colour: (x: number, y: number) => string,
    ): string =>
        cells
            .filter((cell) => glyphs[cell.c])
            .map(
                (cell) =>
                    `<use href="#${key(cell.c)}" x="${n(cell.x)}" y="${n(cell.y)}" fill="${colour(cell.x + CELL_W / 2, cell.y - FONT * 0.35)}"${heavy ? ` stroke="${colour(cell.x + CELL_W / 2, cell.y - FONT * 0.35)}" stroke-width="0.42" stroke-linejoin="round"` : ''}/>`,
            )
            .join('');
    return (
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" ${attrs}>` +
        `<defs>` +
        (paper
            ? `<linearGradient id="${id}-tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbe7f3"/><stop offset="1" stop-color="#ead5f5"/></linearGradient>`
            : `<linearGradient id="${id}-tile" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2a0628"/><stop offset="1" stop-color="#130526"/></linearGradient>`) +
        defs +
        `</defs>` +
        `<rect width="100" height="100" rx="22" fill="url(#${id}-tile)"/>` +
        (paper
            ? `<rect x="1.5" y="1.5" width="97" height="97" rx="20.5" fill="none" stroke="#821574" stroke-opacity="0.35" stroke-width="3"/>`
            : '') +
        uses(ARMS, (x, y) => along(paper ? ARM_PAPER : ARM, [0, 18], [0, 84], [x, y])) +
        uses(FIGURE_CELLS, (x, y) => along(paper ? INK_PAPER : INK, [30, 14], [70, 86], [x, y])) +
        `</svg>`
    );
}
