/* Marbling for the room a chapter's shorter column leaves: ebru, the paper art
   of ink floated on a bath. Drops of the page's inks open one after another, each
   pushing every earlier one outward by the area it takes (Jaffer's marbling map,
   a point at distance d from the drop moves to sqrt(d^2 + r^2)), so the first
   ones thin into rings; now and then a comb is drawn slowly through the bath and
   the rings feather. The pointer drags the ink like a stylus. After a while the
   sheet is lifted (it fades) and a new one comes up.

   Timed in seconds, not frames, so a fast screen does not hurry it. Each pool runs
   only while it is tall enough and on screen; under reduced motion it draws one
   still, combed sheet. */

const INKS = [
    '#db2777',
    '#fdf2f8',
    '#7c3aed',
    '#f5c2e0',
    '#5b1356',
    '#fdf2f8',
    '#c026d3',
    '#f9a8d4',
    '#9333ea',
];
const EDGE = 'rgba(34, 16, 43, 0.14)'; // the fine line where two inks meet
const MIN_HEIGHT = 150; // px of room below which a pool stays empty
const STEP = 2.5; // px: longer edges get a midpoint, so the bands stay smooth
const MAX_POINTS = 24000; // per blot, as numbers (x and y)
const SHARP = 13; // px: a tine's pull halves every this far from it
const SHEET_EVENTS = 30; // drops and combs before the sheet is lifted
const COMB_EVERY = 6; // every sixth event is a comb
const GROW_RATE = 1.5; // per second: how fast a drop closes on its full size
const PAUSE = [1.4, 3] as const; // seconds between one event and the next
const COMB_SECONDS = 5;
const LIFT_SECONDS = 1.8; // the old sheet fading out
const RISE_SECONDS = 1.4; // the new one fading in
const STYLUS = 0.55; // how much of the pointer's motion the ink takes

interface Blot {
    pts: number[];
    colour: string;
}
interface Stir {
    x: number;
    y: number;
    dx: number;
    dy: number;
}
interface Growing {
    x: number;
    y: number;
    r: number;
    to: number;
    blot: Blot;
}
interface Comb {
    vertical: boolean;
    offset: number;
    spacing: number;
    total: number; // px each tine travels
    t: number; // 0 to 1
}

const ring = (x: number, y: number, r: number): number[] => {
    const n = Math.max(64, Math.ceil((2 * Math.PI * r) / STEP));
    const pts: number[] = [];
    for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2;
        pts.push(x + Math.cos(a) * r, y + Math.sin(a) * r);
    }
    return pts;
};
const ease = (t: number): number => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

/** One sheet of marbling, in CSS pixels of a w x h bath. */
class Sheet {
    private blots: Blot[] = [];
    private growing: Growing | undefined;
    private comb: Comb | undefined;
    private colour = Math.floor(Math.random() * INKS.length);
    private spot: { x: number; y: number };
    private events = 0;
    private wait = 0;
    private lift = 0; // seconds left of the fade out
    private rise = 0; // seconds left of the fade in

    constructor(
        private readonly w: number,
        private readonly h: number,
    ) {
        this.spot = { x: w / 2, y: h / 2 };
        this.start();
    }

    private start(): void {
        this.blots = [];
        this.growing = undefined;
        this.comb = undefined;
        this.events = 0;
        this.wait = PAUSE[0];
        // A sheet starts already worked, so it never shows a few lone dots.
        this.settle(16);
    }

    private radius(): number {
        const scale = Math.min(1.4, Math.max(0.7, Math.min(this.w, this.h) / 320));
        return (18 + Math.random() * 40) * scale;
    }

    // Half the drops land in the last one's centre: the bull's-eye rings.
    private nextSpot(): { x: number; y: number } {
        if (Math.random() < 0.5) return this.spot;
        this.spot = {
            x: this.w * (0.18 + Math.random() * 0.64),
            y: this.h * (0.18 + Math.random() * 0.64),
        };
        return this.spot;
    }

    private push(cx: number, cy: number, dr2: number, skip?: Blot): void {
        for (const b of this.blots) {
            if (b === skip) continue;
            const p = b.pts;
            for (let i = 0; i < p.length; i += 2) {
                const dx = p[i]! - cx;
                const dy = p[i + 1]! - cy;
                const d2 = dx * dx + dy * dy;
                if (d2 < 1e-9) continue;
                const k = Math.sqrt(1 + dr2 / d2);
                p[i] = cx + dx * k;
                p[i + 1] = cy + dy * k;
            }
        }
    }

    /** Tines at `offset + k * spacing`, all moved `dz` along their own line. A
        point's distance to the line does not change, so steps simply add up. */
    private tine(c: Comb, dz: number): void {
        for (const b of this.blots) {
            const p = b.pts;
            for (let i = 0; i < p.length; i += 2) {
                const across = c.vertical ? p[i]! : p[i + 1]!;
                const t = (across - c.offset) / c.spacing;
                const f = dz * Math.pow(0.5, (Math.abs(t - Math.round(t)) * c.spacing) / SHARP);
                if (c.vertical) p[i + 1] = p[i + 1]! + f;
                else p[i] = p[i]! + f;
            }
        }
    }

    stylus(s: Stir): void {
        const spread = 2 * 26 * 26;
        for (const b of this.blots) {
            const p = b.pts;
            for (let i = 0; i < p.length; i += 2) {
                const dx = p[i]! - s.x;
                const dy = p[i + 1]! - s.y;
                const f = Math.exp(-(dx * dx + dy * dy) / spread) * STYLUS;
                p[i] = p[i]! + s.dx * f;
                p[i + 1] = p[i + 1]! + s.dy * f;
            }
        }
    }

    private refine(): void {
        const m = 24;
        const inside = (x: number, y: number): boolean =>
            x > -m && x < this.w + m && y > -m && y < this.h + m;
        for (const b of this.blots) {
            const p = b.pts;
            if (p.length > MAX_POINTS) continue;
            const out: number[] = [];
            for (let i = 0; i < p.length; i += 2) {
                const j = (i + 2) % p.length;
                const x = p[i]!;
                const y = p[i + 1]!;
                out.push(x, y);
                const dx = p[j]! - x;
                const dy = p[j + 1]! - y;
                // Only where it can be seen: ink pushed off the sheet stays coarse.
                if (dx * dx + dy * dy > STEP * STEP && (inside(x, y) || inside(p[j]!, p[j + 1]!)))
                    out.push(x + dx / 2, y + dy / 2);
            }
            b.pts = out;
        }
    }

    private dropNow(x: number, y: number, r: number): void {
        this.push(x, y, r * r);
        this.blots.push({ pts: ring(x, y, r), colour: this.nextInk() });
    }

    private nextInk(): string {
        return INKS[this.colour++ % INKS.length]!;
    }

    private newComb(): Comb {
        const sign = Math.random() < 0.5 ? -1 : 1;
        return {
            vertical: Math.random() < 0.5,
            offset: Math.random() * 60,
            spacing: 50 + Math.random() * 30,
            total: sign * (40 + Math.random() * 30),
            t: 0,
        };
    }

    /** `events` drops and combs at once, as the animation would make them. */
    settle(events: number): void {
        for (let e = 1; e <= events; e++) {
            if (e % COMB_EVERY === 0) {
                const comb = this.newComb();
                this.tine(comb, comb.total);
            } else {
                const s = this.nextSpot();
                this.dropNow(s.x, s.y, this.radius());
            }
            this.refine();
        }
    }

    /** Advance by `dt` seconds. Returns the sheet's opacity. */
    step(dt: number): number {
        if (this.lift > 0) {
            this.lift -= dt;
            if (this.lift > 0) return ease(this.lift / LIFT_SECONDS);
            this.start();
            this.rise = RISE_SECONDS;
        }
        if (this.growing) {
            const g = this.growing;
            const r = g.r + (g.to - g.r) * (1 - Math.exp(-GROW_RATE * dt));
            this.push(g.x, g.y, r * r - g.r * g.r, g.blot);
            g.r = r;
            g.blot.pts = ring(g.x, g.y, r);
            if (g.to - r < 0.3) this.growing = undefined;
        } else if (this.comb) {
            // Drawn through slowly, starting and stopping gently.
            const c = this.comb;
            const t = Math.min(1, c.t + dt / COMB_SECONDS);
            this.tine(c, c.total * (ease(t) - ease(c.t)));
            c.t = t;
            if (t >= 1) this.comb = undefined;
        } else if ((this.wait -= dt) <= 0) {
            this.events += 1;
            if (this.events > SHEET_EVENTS) this.lift = LIFT_SECONDS;
            else if (this.events % COMB_EVERY === 0) this.comb = this.newComb();
            else {
                const s = this.nextSpot();
                const blot = { pts: ring(s.x, s.y, 0.5), colour: this.nextInk() };
                this.blots.push(blot);
                this.growing = { x: s.x, y: s.y, r: 0.5, to: this.radius(), blot };
            }
            this.wait = PAUSE[0] + Math.random() * (PAUSE[1] - PAUSE[0]);
        }
        this.refine();
        if (this.rise > 0) {
            this.rise = Math.max(0, this.rise - dt);
            return ease(1 - this.rise / RISE_SECONDS);
        }
        return 1;
    }

    /** Each blot as a smooth closed curve through its points' midpoints, with a
        hairline where it meets the next ink. */
    draw(ctx: CanvasRenderingContext2D): void {
        ctx.clearRect(0, 0, this.w, this.h);
        ctx.lineWidth = 0.6;
        ctx.strokeStyle = EDGE;
        ctx.lineJoin = 'round';
        for (const b of this.blots) {
            const p = b.pts;
            const n = p.length;
            if (n < 6) continue;
            ctx.beginPath();
            ctx.moveTo((p[n - 2]! + p[0]!) / 2, (p[n - 1]! + p[1]!) / 2);
            for (let i = 0; i < n; i += 2) {
                const j = (i + 2) % n;
                ctx.quadraticCurveTo(
                    p[i]!,
                    p[i + 1]!,
                    (p[i]! + p[j]!) / 2,
                    (p[i + 1]! + p[j + 1]!) / 2,
                );
            }
            ctx.closePath();
            ctx.fillStyle = b.colour;
            ctx.fill();
            ctx.stroke();
        }
    }
}

/** Marbling in one pool: sizes itself to the pool, pauses off screen. */
class Pool {
    private readonly canvas: HTMLCanvasElement;
    private ctx: CanvasRenderingContext2D | null = null;
    private sheet: Sheet | undefined;
    private size = { w: 0, h: 0 };
    private onScreen = false;
    private frame = 0;
    private last = 0;
    private stir: Stir | undefined;
    private readonly reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    constructor(private readonly root: HTMLElement) {
        const canvas = root.querySelector('canvas');
        if (!canvas) throw new Error('ebru: no canvas');
        this.canvas = canvas;
        if (!this.reduced && window.matchMedia('(hover: hover)').matches) {
            root.addEventListener('pointermove', (e) => {
                const b = this.canvas.getBoundingClientRect();
                const x = e.clientX - b.left;
                const y = e.clientY - b.top;
                const s = this.stir;
                this.stir = s
                    ? { x, y, dx: s.dx + x - s.x, dy: s.dy + y - s.y }
                    : { x, y, dx: 0, dy: 0 };
            });
            root.addEventListener('pointerleave', () => (this.stir = undefined));
        }
    }

    fit(): void {
        const w = Math.round(this.canvas.clientWidth);
        const h = Math.round(this.canvas.clientHeight);
        if (w === this.size.w && h === this.size.h) return;
        this.size = { w, h };
        const tall = h >= MIN_HEIGHT && w > 0;
        this.root.classList.toggle('is-live', tall);
        this.sheet = undefined;
        if (!tall) {
            this.update();
            return;
        }
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.canvas.width = Math.round(w * dpr);
        this.canvas.height = Math.round(h * dpr);
        this.ctx = this.canvas.getContext('2d');
        if (!this.ctx) return;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.sheet = new Sheet(w, h);
        if (this.reduced) this.sheet.settle(8);
        this.sheet.draw(this.ctx);
        this.update();
    }

    setOnScreen(on: boolean): void {
        this.onScreen = on;
        this.update();
    }

    update(): void {
        const run = Boolean(this.sheet) && this.onScreen && !document.hidden && !this.reduced;
        if (run && !this.frame) {
            this.last = 0;
            this.frame = requestAnimationFrame(this.tick);
        }
        if (!run && this.frame) {
            cancelAnimationFrame(this.frame);
            this.frame = 0;
        }
    }

    private readonly tick = (now: number): void => {
        this.frame = 0;
        const sheet = this.sheet;
        const ctx = this.ctx;
        if (!sheet || !ctx) return;
        // A long gap (a stalled tab) counts as one ordinary frame, not a jump.
        const dt = this.last ? Math.min(0.05, (now - this.last) / 1000) : 1 / 60;
        this.last = now;
        const s = this.stir;
        if (s && (s.dx || s.dy)) {
            sheet.stylus(s);
            this.stir = { ...s, dx: 0, dy: 0 };
        }
        this.canvas.style.opacity = String(sheet.step(dt));
        sheet.draw(ctx);
        this.update();
    };
}

export function initEbru(): void {
    const byRoot = new Map<Element, Pool>();
    for (const el of document.querySelectorAll<HTMLElement>('[data-ebru]')) {
        try {
            byRoot.set(el, new Pool(el));
        } catch {
            // No canvas in it: the pool stays empty.
        }
    }
    if (!byRoot.size) return;
    const resize = new ResizeObserver((entries) => {
        for (const entry of entries) byRoot.get(entry.target)?.fit();
    });
    const seen = new IntersectionObserver(
        (entries) => {
            for (const entry of entries)
                byRoot.get(entry.target)?.setOnScreen(entry.isIntersecting);
        },
        { rootMargin: '100px 0px' },
    );
    for (const root of byRoot.keys()) {
        resize.observe(root);
        seen.observe(root);
    }
    document.addEventListener('visibilitychange', () => byRoot.forEach((p) => p.update()));
}
