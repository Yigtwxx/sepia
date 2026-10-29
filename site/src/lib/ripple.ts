/* Ripples from the pointer: rings that bend the picture and catch the light.

   A port of src/sepia/ripple.py, with its constants. Each ring grows out of the
   cell where the pointer dropped it; its slope moves the picture a cell or two
   along its own radius, as a lens would, and its crest and troughs shift the
   colours. The viewer lifts a crest toward white on a black terminal; on paper
   the page darkens a crest toward ink and pales the troughs toward the sheet. */

/** Cells are about twice as tall as wide; distances are in cell widths. */
export const ASPECT = 2.0;
/** How far a ring travels before it is gone, in cell widths. */
export const REACH = 25.0;
/** Seconds a ring lives. */
export const DURATION = 1.0;
/** Half-width of a ring's crest, in cell widths. */
export const WIDTH = 3.5;
/** How far the steepest part of a fresh ring moves the picture, in cell widths. */
export const MAX_SHIFT = 3.0;
/** How far a fresh crest moves a cell's colours. */
export const LIGHT = 0.8;
/** How far the pointer moves before it drops the next ring, in cell widths. */
export const DROP_SPACING = 5.0;
/** Rings alive at once; a new one replaces the oldest. */
export const MAX_RIPPLES = 8;

const EDGE = 3.0;
const SLOPE_PEAK = Math.SQRT2 * Math.exp(-0.5);
/** Light below this share does not show and is not drawn. */
export const FAINT = 0.02;

export interface Ripple {
    col: number;
    row: number;
    /** Seconds, on the same clock as `now`. */
    born: number;
}

/** Whether the pointer at (col, row) is far enough from the last drop for a ring. */
export function spaced(
    last: { col: number; row: number } | null,
    col: number,
    row: number,
): boolean {
    if (!last) return true;
    return Math.hypot(col - last.col, (row - last.row) * ASPECT) >= DROP_SPACING;
}

/** One frame's bend and light, per cell. Reused between frames. */
export class RippleField {
    readonly shiftX: Float32Array;
    readonly shiftY: Float32Array;
    readonly light: Float32Array;

    constructor(
        readonly cols: number,
        readonly rows: number,
    ) {
        const n = cols * rows;
        this.shiftX = new Float32Array(n);
        this.shiftY = new Float32Array(n);
        this.light = new Float32Array(n);
    }

    /** Fill the field for `ripples` at `now`; true if any ring is alive. */
    compute(ripples: readonly Ripple[], now: number): boolean {
        this.shiftX.fill(0);
        this.shiftY.fill(0);
        this.light.fill(0);
        let alive = false;
        for (const ripple of ripples) alive = this.add(ripple, now) || alive;
        return alive;
    }

    private add(ripple: Ripple, now: number): boolean {
        const age = now - ripple.born;
        if (!(age >= 0 && age < DURATION)) return false;
        const fade = 1 - age / DURATION;
        const radius = (REACH * age) / DURATION;
        const outer = radius + EDGE * WIDTH;
        const top = Math.max(Math.floor(ripple.row - outer / ASPECT), 0);
        const bottom = Math.min(Math.ceil(ripple.row + outer / ASPECT) + 1, this.rows);
        const left = Math.max(Math.floor(ripple.col - outer), 0);
        const right = Math.min(Math.ceil(ripple.col + outer) + 1, this.cols);
        for (let y = top; y < bottom; y++) {
            for (let x = left; x < right; x++) {
                const dx = x - ripple.col;
                const dy = (y - ripple.row) * ASPECT;
                const distance = Math.hypot(dx, dy);
                const u = (distance - radius) / WIDTH;
                const crest = Math.exp(-u * u);
                const push = (MAX_SHIFT * fade * 2 * u * crest) / SLOPE_PEAK;
                const reach = Math.max(distance, 1e-9);
                const i = y * this.cols + x;
                this.shiftX[i] = (this.shiftX[i] ?? 0) + (push * dx) / reach;
                this.shiftY[i] = (this.shiftY[i] ?? 0) + (push * dy) / reach / ASPECT;
                this.light[i] = (this.light[i] ?? 0) + LIGHT * fade * (1 - 2 * u * u) * crest;
            }
        }
        return true;
    }

    /** The cell a ripple shows at (x, y), and its light, clamped like the viewer's. */
    sample(x: number, y: number): { from: number; light: number } {
        const i = y * this.cols + x;
        const sx = Math.min(this.cols - 1, Math.max(0, Math.round(x + (this.shiftX[i] ?? 0))));
        const sy = Math.min(this.rows - 1, Math.max(0, Math.round(y + (this.shiftY[i] ?? 0))));
        let light = Math.min(1, Math.max(-1, this.light[i] ?? 0));
        if (Math.abs(light) < FAINT) light = 0;
        return { from: sy * this.cols + sx, light };
    }
}
