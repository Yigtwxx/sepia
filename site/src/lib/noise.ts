/* Deterministic randomness for the canvases: the same page draws the same marks
   on every load. */

/** A stable pseudo-random number in [0, 1) for an integer. */
export function hash(i: number): number {
    let x = Math.imul(i ^ 0x9e3779b9, 0x85ebca6b);
    x ^= x >>> 13;
    x = Math.imul(x, 0xc2b2ae35);
    x ^= x >>> 16;
    return (x >>> 0) / 4294967296;
}

/** Smooth value noise in [0, 1): currents for skins, ink and paper fibres. */
export function noise(x: number, y: number): number {
    const xi = Math.floor(x);
    const yi = Math.floor(y);
    const fx = x - xi;
    const fy = y - yi;
    const corner = (i: number, j: number): number =>
        hash(Math.imul(xi + i, 73856093) ^ Math.imul(yi + j, 19349663));
    const u = fx * fx * (3 - 2 * fx);
    const v = fy * fy * (3 - 2 * fy);
    const top = corner(0, 0) + (corner(1, 0) - corner(0, 0)) * u;
    const bottom = corner(0, 1) + (corner(1, 1) - corner(0, 1)) * u;
    return top + (bottom - top) * v;
}
