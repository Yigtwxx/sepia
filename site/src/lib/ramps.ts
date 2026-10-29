/* The viewer's character ramps and colour rules, for the canvas.

   A mirror of src/sepia/ascii_art.py: the same characters with the share of a
   cell their ink covers, the same 4x4 Bayer dither and the same ink and fill
   colours. scripts/site_art.py draws every picture with the Python originals;
   the canvas only needs these to redraw a cell that a ripple, a passing cloud or
   a jet of ink has changed, and to switch a picture between styles. */

export type Charset = 'classic' | 'symbols';
export type ArtStyle = 'ink' | 'fill';
export type Rgb = readonly [number, number, number];

const CLASSIC: readonly (readonly [string, number])[] = [
    [' ', 0.0],
    ['`', 0.076],
    ["'", 0.133],
    ['-', 0.157],
    [',', 0.177],
    ['_', 0.2],
    ['^', 0.246],
    ['"', 0.262],
    ['!', 0.29],
    ['<', 0.347],
    ['+', 0.365],
    ['?', 0.41],
    ['|', 0.427],
    ['c', 0.443],
    ['(', 0.475],
    ['i', 0.491],
    ['}', 0.507],
    ['n', 0.529],
    ['f', 0.545],
    ['o', 0.575],
    ['a', 0.6],
    ['X', 0.622],
    ['w', 0.651],
    ['b', 0.695],
    ['O', 0.734],
    ['%', 0.763],
    ['8', 0.792],
    ['0', 0.812],
    ['W', 0.839],
    ['Q', 0.875],
    ['@', 1.0],
];

const SYMBOLS: readonly (readonly [string, number])[] = [
    [' ', 0.0],
    ['.', 0.08],
    ["'", 0.15],
    [':', 0.16],
    [';', 0.24],
    ['^', 0.27],
    ['!', 0.29],
    ['~', 0.3],
    ['+', 0.39],
    ['*', 0.45],
    ['(', 0.55],
    ['%', 0.8],
    ['#', 0.81],
    ['&', 0.87],
    ['@', 1.0],
];

export interface Ramp {
    chars: readonly string[];
    density: readonly number[];
    /** Character to its ink share, for reading a drawn plate back into densities. */
    lookup: ReadonlyMap<string, number>;
}

function ramp(entries: readonly (readonly [string, number])[]): Ramp {
    return {
        chars: entries.map(([c]) => c),
        density: entries.map(([, d]) => d),
        lookup: new Map(entries.map(([c, d]) => [c, d])),
    };
}

export const RAMPS: Readonly<Record<Charset, Ramp>> = {
    classic: ramp(CLASSIC),
    symbols: ramp(SYMBOLS),
};

/** Ordered-dither amplitude added to mid-tone densities before a symbol is picked. */
export const DITHER = 0.05;
/** Thin glyphs show less colour than a filled cell, so ink colours are pushed. */
export const SATURATION_BOOST = 1.2;
/** Lowest brightness of an ink colour (its strongest channel, 0..1). */
export const INK_FLOOR = 0.55;
/** Brightness of the painted background in `fill` style, relative to the cell. */
export const FILL_BACKGROUND = 0.55;
/** How far `fill` symbols are mixed toward white. */
export const FILL_HIGHLIGHT = 0.35;

// 4x4 Bayer matrix, centred on zero so dithering does not shift brightness.
const BAYER: readonly (readonly number[])[] = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
].map((row) => row.map((v) => (v + 0.5) / 16 - 0.5));

/** The character whose ink share is closest to `density`, after the dither. */
export function pickChar(density: number, row: number, col: number, charset: Charset): string {
    const midtone = 4 * density * (1 - density);
    const target = density + (BAYER[row % 4]?.[col % 4] ?? 0) * 2 * DITHER * midtone;
    const { chars, density: shares } = RAMPS[charset];
    let best = 0;
    let gap = Infinity;
    for (let i = 0; i < shares.length; i++) {
        const d = Math.abs(target - (shares[i] ?? 0));
        if (d < gap) {
            gap = d;
            best = i;
        }
    }
    return chars[best] ?? ' ';
}

/** The ink share of a drawn character (0 for anything not on the ramp). */
export function shareOf(char: string, charset: Charset = 'classic'): number {
    return RAMPS[charset].lookup.get(char) ?? 0;
}

const luma = (r: number, g: number, b: number): number => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));
const toByte = (v: number): number => Math.min(255, Math.max(0, Math.round(v * 255)));

/** `ink` style: the cell's glow, more saturated, lifted so dark cells still show. */
export function inkColor(glow: Rgb): Rgb {
    const [r, g, b] = glow.map((v) => v / 255) as [number, number, number];
    const gray = luma(r, g, b);
    const s = [r, g, b].map((c) => clamp01(gray + (c - gray) * SATURATION_BOOST));
    const value = Math.max(...s);
    const scale = value > 0.02 ? (INK_FLOOR + (1 - INK_FLOOR) * value) / value : 1;
    return s.map((c) => toByte(clamp01(c * scale))) as unknown as Rgb;
}

/** `fill` style: a bright symbol on a darkened copy of the cell's own colour. */
export function fillColors(glow: Rgb, cell: Rgb): { fg: Rgb; bg: Rgb } {
    const fg = glow.map((v) => toByte(v / 255 + (1 - v / 255) * FILL_HIGHLIGHT)) as unknown as Rgb;
    const bg = cell.map((v) => toByte((v / 255) * FILL_BACKGROUND)) as unknown as Rgb;
    return { fg, bg };
}
