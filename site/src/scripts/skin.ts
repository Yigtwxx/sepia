/* The plate's skin: a ring of chromatophores between the frame's two rules.

   A cuttlefish colours itself with thousands of pigment cells, each a sac a
   muscle can pull open into a disc of colour or let close to a dot. The frame
   carries a ring of them. At rest they are small and pale; when the plate
   surfaces, when the reader's pointer arrives, and with every passing cloud on
   the hero, a flush runs round the ring from the nearest point: the cells open,
   darken to violet and close again behind it.

   Drawn on its own canvas over the frame; without the script the frame shows a
   plain dotted band (Inkprint.astro). Under reduced motion it draws once, still. */
import type { Rgb } from '../lib/ramps';

const SPACING = 11; // px between cells along the ring
const REST = 1.35; // px radius of a closed cell
const OPEN = 3.6; // px radius of a fully open one
const SPEED = 900; // px of ring the flush covers per second
const PULSE_MS = 720; // how long one cell stays open
const FRAME_MS = 1000 / 30;

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
];

interface Cell {
    x: number;
    y: number;
    /** Distance along the ring from its top-left corner, in px. */
    s: number;
    base: Rgb;
    jitter: number;
}

interface Flush {
    from: number; // ring position the wave starts at
    born: number; // ms
}

export interface SkinTones {
    rest: readonly Rgb[];
    open: Rgb;
}

export class Skin {
    private ctx: CanvasRenderingContext2D;
    private cells: Cell[] = [];
    private flushes: Flush[] = [];
    private perimeter = 0;
    private frame = 0;
    private last = 0;
    private width = 0;
    private height = 0;
    private readonly reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    constructor(
        private canvas: HTMLCanvasElement,
        /** Inset of the ring's centre line from the canvas edge, in px. */
        private inset: () => number,
        private tones: SkinTones,
    ) {
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('skin: no 2d context');
        this.ctx = ctx;
    }

    fit(): void {
        const box = this.canvas.getBoundingClientRect();
        if (box.width === 0) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.width = box.width;
        this.height = box.height;
        this.canvas.width = Math.round(box.width * dpr);
        this.canvas.height = Math.round(box.height * dpr);
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.layout();
        this.draw(performance.now());
    }

    /** Cells evenly round a rectangle; corners get one cell each. */
    private layout(): void {
        const m = this.inset();
        const w = this.width - 2 * m;
        const h = this.height - 2 * m;
        this.perimeter = 2 * (w + h);
        const count = Math.max(8, Math.round(this.perimeter / SPACING));
        const step = this.perimeter / count;
        const ramp = this.tones.rest;
        this.cells = [];
        for (let k = 0; k < count; k++) {
            const s = k * step;
            let x: number;
            let y: number;
            if (s < w) [x, y] = [m + s, m];
            else if (s < w + h) [x, y] = [m + w, m + (s - w)];
            else if (s < 2 * w + h) [x, y] = [m + w - (s - w - h), m + h];
            else [x, y] = [m, m + h - (s - 2 * w - h)];
            // The resting colour runs the ramp once round the ring, out and back,
            // so the two halves meet without a seam.
            const t = 1 - Math.abs((s / this.perimeter) * 2 - 1);
            const scaled = t * (ramp.length - 1);
            const i = Math.floor(scaled);
            const base = mix(ramp[i] ?? ramp[0]!, ramp[i + 1] ?? ramp[i]!, scaled - i);
            this.cells.push({ x, y, s, base, jitter: ((k * 2654435761) >>> 0) / 4294967296 });
        }
    }

    /** Send a flush round the ring from the point nearest (fx, fy), as fractions. */
    flush(fx = 0.5, fy = 0): void {
        if (this.reduced || this.cells.length === 0) return;
        const x = fx * this.width;
        const y = fy * this.height;
        let best = 0;
        let gap = Infinity;
        for (const cell of this.cells) {
            const d = Math.hypot(cell.x - x, cell.y - y);
            if (d < gap) {
                gap = d;
                best = cell.s;
            }
        }
        this.flushes.push({ from: best, born: performance.now() });
        if (this.flushes.length > 3) this.flushes.shift();
        if (!this.frame) this.frame = requestAnimationFrame(this.tick);
    }

    private tick = (ms: number): void => {
        this.frame = 0;
        if (ms - this.last >= FRAME_MS - 1) {
            this.last = ms;
            this.draw(ms);
        }
        const span = (this.perimeter / 2 / SPEED) * 1000 + PULSE_MS;
        this.flushes = this.flushes.filter((f) => ms - f.born < span);
        if (this.flushes.length) this.frame = requestAnimationFrame(this.tick);
        else this.draw(ms);
    };

    private draw(ms: number): void {
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.width, this.height);
        for (const cell of this.cells) {
            let open = 0;
            for (const f of this.flushes) {
                // The wave runs both ways round the ring from where it started.
                const along = Math.abs(cell.s - f.from);
                const ring = Math.min(along, this.perimeter - along);
                const t = (ms - f.born - (ring / SPEED) * 1000 - cell.jitter * 90) / PULSE_MS;
                if (t > 0 && t < 1) open = Math.max(open, Math.sin(Math.PI * t) ** 1.5);
            }
            const r = REST + (OPEN - REST) * open;
            ctx.fillStyle = (() => {
                const c = mix(cell.base, this.tones.open, open);
                return `rgb(${c[0] | 0} ${c[1] | 0} ${c[2] | 0})`;
            })();
            ctx.beginPath();
            ctx.arc(cell.x, cell.y, r, 0, Math.PI * 2);
            ctx.fill();
        }
    }
}
