/* A picture made of characters, on a canvas, alive.

   The characters come from scripts/site_art.py, which draws every plate and
   picture with sepia's own code; the canvas starts from exactly that text and only
   changes a cell when something moves it:

   - the skin: on the hero, the animal's colours drift the way a cuttlefish's
     chromatophores do, slow currents of pink and violet over a still drawing, and
     now and then a dark cloud passes over it;
   - touch: around the pointer the pigment gathers, the cells nearby darken and
     thicken, and follow the pointer with a little lag;
   - ripples: as the pointer moves it drops rings, the viewer's own (lib/ripple.ts);
   - ink: a click releases a cloud that billows, drifts and thins out, packing the
     cells it covers into dense glyphs on the way;
   - the reveal: when a plate scrolls in, its cells soak up their ink from a point,
     along an uneven front, each one climbing the ramp from a blank to its glyph.

   Two looks. A plate is ink on paper (or pink on the orchid field), coloured by the
   page's ink ramp. A picture is the viewer's: its own colours on black, in the ink
   or fill style, with the viewer's ripple shading.

   Without the script the <pre> under the canvas shows the same characters; with
   reduced motion the canvas draws the finished picture once and stays still. */
import {
    fillColors,
    inkColor,
    pickChar,
    shareOf,
    type ArtStyle,
    type Charset,
    type Rgb,
} from '../lib/ramps';
import { RippleField, spaced, MAX_RIPPLES, type Ripple } from '../lib/ripple';
import { hash, noise } from '../lib/noise';

export interface PictureColours {
    cols: number;
    rows: number;
    cell: string;
    glow: string;
}

type Look = 'paper' | 'field' | 'screen';

interface Jet {
    col: number;
    row: number;
    born: number;
    /** Unit vector the cloud drifts along. */
    dx: number;
    dy: number;
    seed: number;
}

const FRAME_MS = 1000 / 30;
const REVEAL_MS = 1600;
const SOAK_MS = 340; // how long one cell takes to climb the ramp to its glyph
const JET_SECONDS = 2.6;
const CLOUD_EVERY = 5.5; // seconds between passing clouds
const CLOUD_SECONDS = 2.8;
const CLOUD_WIDTH = 6; // half-width of the band, in cell widths
const TOUCH_RADIUS = 7; // cell widths
const TOUCH_EASE = 0.22; // share of the way to the pointer covered each frame

const INK_DEEP: Rgb = [46, 10, 63];
const CLOUD_TONE: Rgb = [70, 12, 96];
const TOUCH_TONE: Rgb = [109, 40, 217];
const WHITE: Rgb = [255, 255, 255];
const BLACK: Rgb = [0, 0, 0];

// The page's ramp on paper (tokens.css --ramp-*) and the prompt window's bands on
// the orchid field (src/sepia/ui.py BANDS).
const PAPER_RAMP: readonly Rgb[] = [
    [219, 39, 119],
    [192, 38, 211],
    [147, 51, 234],
    [124, 58, 237],
    [91, 33, 182],
];
const FIELD_RAMP: readonly Rgb[] = [
    [249, 168, 212],
    [244, 114, 182],
    [232, 121, 249],
    [192, 132, 252],
    [167, 139, 250],
];
const PAPER: Rgb = [236, 208, 227]; // tokens.css --paper
const ORCHID: Rgb = [91, 19, 86];
const CREAM: Rgb = [253, 242, 248];

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
];
const css = (c: Rgb): string => `rgb(${c[0] | 0} ${c[1] | 0} ${c[2] | 0})`;
const smooth = (t: number): number => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));

function rampAt(ramp: readonly Rgb[], t: number): Rgb {
    const scaled = Math.min(0.9999, Math.max(0, t)) * (ramp.length - 1);
    const i = Math.floor(scaled);
    return mix(ramp[i] ?? ramp[0]!, ramp[i + 1] ?? ramp[i]!, scaled - i);
}

function decode(b64: string): Uint8Array {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
}

export interface FieldOptions {
    look: Look;
    /** The drawn text, one line per row (shorter lines are padded with blanks). */
    text: string;
    cols: number;
    rows: number;
    /** Where the reveal starts, as fractions of the plate. */
    origin?: [number, number];
    reveal?: boolean;
    ripples?: boolean;
    jets?: boolean;
    /** The living skin: drifting colour and passing clouds (the hero). */
    clouds?: boolean;
    charset?: Charset;
    /** Called as each passing cloud starts, so the frame's skin can flush with it. */
    onCloud?: () => void;
}

export class InkField {
    private ctx: CanvasRenderingContext2D;
    private cols: number;
    private rows: number;
    private chars: string[] = [];
    private share: Float32Array;
    /** Each cell's place on the ink ramp, 0 (pink) to 1 (violet). */
    private tone: Float32Array;
    private colours: Rgb[] = [];
    private backs: (Rgb | null)[] = [];
    private glow: Uint8Array | null = null;
    private cell: Uint8Array | null = null;
    private texts: Partial<Record<Charset, string>> = {};
    private charset: Charset;
    private style: ArtStyle = 'ink';
    private field: RippleField;
    private ripples: Ripple[] = [];
    private lastDrop: { col: number; row: number } | null = null;
    private jets: Jet[] = [];
    private revealAt: Float32Array | null = null;
    private revealStart = -1;
    private revealMs = REVEAL_MS;
    private cloudStart = -1;
    private nextCloud = 2.4;
    private pointer: { col: number; row: number } | null = null;
    private touch = { col: 0, row: 0, presence: 0 };
    private visible = false;
    private paused = false;
    private wasMoving = false;
    private cloudTimer = 0;
    private frame = 0;
    private lastPaint = 0;
    private cellW = 0;
    readonly reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    constructor(
        private canvas: HTMLCanvasElement,
        private options: FieldOptions,
    ) {
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('ink-field: no 2d context');
        this.ctx = ctx;
        this.cols = options.cols;
        this.rows = options.rows;
        this.charset = options.charset ?? 'classic';
        this.share = new Float32Array(this.cols * this.rows);
        this.tone = new Float32Array(this.cols * this.rows);
        this.field = new RippleField(this.cols, this.rows);
        this.setText(options.text);
        if (options.look !== 'screen') this.paintRamp();
        if (options.reveal && !this.reduced) this.planReveal(options.origin ?? [0.5, 0.45]);
        this.listen();
    }

    /** Swap in the drawn text (a charset change on a picture). */
    setText(text: string): void {
        const lines = text.split('\n');
        this.chars = [];
        for (let y = 0; y < this.rows; y++) {
            const line = lines[y] ?? '';
            for (let x = 0; x < this.cols; x++) {
                const c = line[x] ?? ' ';
                this.chars.push(c);
                this.share[y * this.cols + x] = shareOf(c, this.charset);
            }
        }
    }

    /** A picture's own colours (public/art/<id>.json) and both charsets' text. */
    setPicture(colours: PictureColours, texts: Partial<Record<Charset, string>>): void {
        this.cell = decode(colours.cell);
        this.glow = decode(colours.glow);
        this.texts = texts;
        const text = texts[this.charset];
        if (text) this.setText(text);
        this.paintScreen();
        this.draw(performance.now());
    }

    /** An empty screen: the viewer before its first picture. */
    clear(): void {
        this.setText('');
        this.revealStart = -1;
        this.draw(performance.now());
    }

    /** Draw the current picture in again, soaking in from `origin`. */
    revealFrom(origin: [number, number], ms = REVEAL_MS): void {
        this.revealMs = ms;
        if (this.reduced) {
            this.draw(performance.now());
            return;
        }
        this.planReveal(origin);
        this.revealStart = performance.now();
        this.wasMoving = true;
        this.kick();
    }

    setLook(style: ArtStyle, charset: Charset): void {
        this.style = style;
        if (charset !== this.charset) {
            this.charset = charset;
            const text = this.texts[charset];
            if (text) this.setText(text);
        }
        this.paintScreen();
        this.draw(performance.now());
    }

    setPaused(paused: boolean): void {
        this.paused = paused;
        if (paused) {
            this.cloudStart = -1;
            window.clearTimeout(this.cloudTimer);
            this.cloudTimer = 0;
        } else {
            this.nextCloud = performance.now() / 1000 + 0.8;
        }
        this.wasMoving = true; // redraw once, so the skin settles where it stopped
        this.kick();
    }

    /** Lay the canvas out to its box; call on resize. */
    fit(): void {
        const width = this.canvas.clientWidth;
        if (width === 0) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.cellW = width / this.cols;
        const height = this.cellW * 2 * this.rows;
        this.canvas.width = Math.round(width * dpr);
        this.canvas.height = Math.round(height * dpr);
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        // IBM Plex Mono advances 0.6 em, so this font fills a cell's width.
        this.ctx.font = `500 ${(this.cellW / 0.6).toFixed(2)}px 'IBM Plex Mono', ui-monospace, monospace`;
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.draw(performance.now());
    }

    /** Start drawing: the reveal, then whatever stays alive. */
    start(): void {
        // The reveal's clock starts first: the layout's own first frame is then
        // already the reveal's, not a flash of the finished plate.
        if (this.revealAt) this.revealStart = performance.now();
        this.fit();
        this.kick();
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        this.kick();
    }

    private paintRamp(): void {
        const ramp = this.options.look === 'field' ? FIELD_RAMP : PAPER_RAMP;
        this.colours = [];
        for (let y = 0; y < this.rows; y++) {
            for (let x = 0; x < this.cols; x++) {
                // Pink at the top left to violet at the bottom right: the wordmark's
                // bands, run on a diagonal so a tall plate gets all of them.
                const t = (x / this.cols) * 0.62 + (y / this.rows) * 0.38;
                this.tone[y * this.cols + x] = t;
                this.colours.push(rampAt(ramp, t));
            }
        }
    }

    private paintScreen(): void {
        if (!this.glow || !this.cell) return;
        this.colours = [];
        this.backs = [];
        for (let i = 0; i < this.cols * this.rows; i++) {
            const o = i * 3;
            const glow: Rgb = [this.glow[o] ?? 0, this.glow[o + 1] ?? 0, this.glow[o + 2] ?? 0];
            if (this.style === 'fill') {
                const cell: Rgb = [this.cell[o] ?? 0, this.cell[o + 1] ?? 0, this.cell[o + 2] ?? 0];
                const { fg, bg } = fillColors(glow, cell);
                this.colours.push(fg);
                this.backs.push(bg);
            } else {
                this.colours.push(inkColor(glow));
                this.backs.push(null);
            }
        }
    }

    /** When each cell starts to soak: distance from the origin, on an uneven front. */
    private planReveal([ox, oy]: [number, number]): void {
        const at = new Float32Array(this.cols * this.rows);
        const cx = ox * this.cols;
        const cy = oy * this.rows * 2;
        const far = Math.hypot(Math.max(cx, this.cols - cx), Math.max(cy, this.rows * 2 - cy));
        for (let y = 0; y < this.rows; y++) {
            for (let x = 0; x < this.cols; x++) {
                const d = Math.hypot(x - cx, y * 2 - cy) / far;
                // The front frays like ink running along the fibres of the paper.
                const fray = noise(x * 0.11, y * 0.22) * 0.32 + hash(y * this.cols + x) * 0.06;
                at[y * this.cols + x] = (d * 0.66 + fray) * this.revealMs;
            }
        }
        this.revealAt = at;
    }

    private cellAt(event: PointerEvent): { col: number; row: number } | null {
        const box = this.canvas.getBoundingClientRect();
        if (box.width === 0) return null;
        const col = ((event.clientX - box.left) / box.width) * this.cols;
        const row = ((event.clientY - box.top) / box.height) * this.rows;
        if (col < 0 || row < 0 || col >= this.cols || row >= this.rows) return null;
        return { col, row };
    }

    private listen(): void {
        const opts = this.options;
        if (this.reduced || (!opts.ripples && !opts.jets)) return;
        if (opts.ripples) {
            this.canvas.addEventListener('pointermove', (event) => {
                if (event.pointerType === 'touch') return;
                const at = this.cellAt(event);
                if (!at) return;
                if (!this.pointer) {
                    this.touch.col = at.col;
                    this.touch.row = at.row;
                }
                this.pointer = at;
                const cell = { col: Math.floor(at.col), row: Math.floor(at.row) };
                if (spaced(this.lastDrop, cell.col, cell.row)) {
                    this.lastDrop = cell;
                    this.ripples.push({ ...cell, born: performance.now() / 1000 });
                    if (this.ripples.length > MAX_RIPPLES) this.ripples.shift();
                }
                this.kick();
            });
            this.canvas.addEventListener('pointerleave', () => {
                this.pointer = null;
                this.lastDrop = null;
                this.kick();
            });
        }
        if (opts.jets) {
            this.canvas.addEventListener('pointerdown', (event) => {
                const at = this.cellAt(event);
                if (!at) return;
                // Ink leaves backwards from the siphon: up and away from the arms for
                // a plate seen from above, with a little scatter.
                const angle = -Math.PI / 2 + (Math.random() - 0.5) * 1.4;
                this.jets.push({
                    col: at.col,
                    row: at.row,
                    born: performance.now() / 1000,
                    dx: Math.cos(angle),
                    dy: Math.sin(angle),
                    seed: Math.random() * 1000,
                });
                if (this.jets.length > 4) this.jets.shift();
                this.kick();
            });
        }
    }

    /** Make sure a frame is coming if anything could move. */
    private kick(): void {
        if (this.frame || this.reduced) return;
        this.frame = requestAnimationFrame(this.tick);
    }

    private tick = (ms: number): void => {
        this.frame = 0;
        if (!this.visible || document.hidden) return;
        const moving = this.moving();
        // One more frame after the last thing stops, so the picture heals.
        if ((moving || this.wasMoving) && ms - this.lastPaint >= FRAME_MS - 1) {
            this.lastPaint = ms;
            this.draw(ms);
            this.wasMoving = moving;
        }
        if (moving || this.wasMoving) this.frame = requestAnimationFrame(this.tick);
    };

    /** The hero's skin moves on its own while it is on screen and not paused. */
    private get living(): boolean {
        return Boolean(this.options.clouds) && !this.paused && !this.reduced;
    }

    private moving(): boolean {
        if (this.revealStart >= 0) return true;
        if (this.ripples.length || this.jets.length) return true;
        if (this.pointer || this.touch.presence > 0.01) return true;
        return this.living;
    }

    private cloudBand(now: number): ((x: number, y: number) => number) | null {
        if (!this.living) return null;
        if (this.cloudStart < 0) {
            if (now < this.nextCloud) return null;
            this.cloudStart = now;
            this.options.onCloud?.();
        }
        const t = (now - this.cloudStart) / CLOUD_SECONDS;
        if (t >= 1) {
            this.cloudStart = -1;
            this.nextCloud = now + CLOUD_EVERY;
            return null;
        }
        // The band runs head to tail, top to bottom, its edge rippling as it goes.
        const span = this.rows * 2 + this.cols * 0.35 + CLOUD_WIDTH * 4;
        const pos = smooth(t) * span - CLOUD_WIDTH * 2;
        const strength = Math.sin(Math.PI * t);
        return (x, y) => {
            const wave = (noise(x * 0.09, now * 0.8) - 0.5) * 5;
            const u = (y * 2 + x * 0.35 + wave - pos) / CLOUD_WIDTH;
            return strength * Math.exp(-u * u);
        };
    }

    private jetInk(x: number, y: number, now: number): number {
        let ink = 0;
        for (const jet of this.jets) {
            const age = (now - jet.born) / JET_SECONDS;
            const fade = Math.pow(1 - age, 1.25);
            // Three puffs along the drift, each larger, later and fainter than the last.
            for (let k = 0; k < 3; k++) {
                const travel = k * 2.4 + Math.sqrt(age) * (4 + 3 * k);
                const cx = jet.col + jet.dx * travel * 1.6;
                const cy = jet.row + jet.dy * travel * 0.8;
                const radius = (3.2 + 2.6 * k) * Math.sqrt(Math.min(1, age * 1.6)) + 1.2;
                const d = Math.hypot(x - cx, (y - cy) * 2);
                const billow = 0.7 + 0.6 * noise(x * 0.32 + jet.seed, y * 0.64 - age * 3 + k * 7);
                const edge = radius * billow;
                if (d >= edge) continue;
                ink = Math.max(ink, smooth(1 - d / edge) * fade * (1 - 0.22 * k));
            }
        }
        return Math.min(1, ink);
    }

    private draw(ms: number): void {
        const ctx = this.ctx;
        const w = this.cellW;
        if (w === 0) return;
        const h = w * 2;
        const now = ms / 1000;
        const look = this.options.look;
        const paper = look === 'paper';
        const screen = look === 'screen';
        const ramp = look === 'field' ? FIELD_RAMP : PAPER_RAMP;
        this.ripples = this.ripples.filter((r) => now - r.born < 1);
        this.jets = this.jets.filter((j) => now - j.born < JET_SECONDS);
        const rippling = this.ripples.length > 0 && this.field.compute(this.ripples, now);
        const band = screen ? null : this.cloudBand(now);
        const elapsed = this.revealStart >= 0 ? ms - this.revealStart : Infinity;
        if (this.revealAt && elapsed > this.revealMs + SOAK_MS) this.revealStart = -1;
        const revealing = this.revealAt !== null && this.revealStart >= 0;
        const living = this.living && !screen;
        const jetting = this.jets.length > 0 && !screen;

        // The pigment under the pointer follows it with a little lag, and gathers
        // or fades as the pointer arrives or leaves.
        const touch = this.touch;
        if (this.pointer) {
            touch.col += (this.pointer.col - touch.col) * TOUCH_EASE;
            touch.row += (this.pointer.row - touch.row) * TOUCH_EASE;
        }
        touch.presence += ((this.pointer ? 1 : 0) - touch.presence) * 0.12;
        const touching = !screen && touch.presence > 0.01;

        ctx.clearRect(0, 0, this.cols * w, this.rows * h);
        let lastFill = '';
        for (let y = 0; y < this.rows; y++) {
            for (let x = 0; x < this.cols; x++) {
                const at = y * this.cols + x;
                let i = at;
                let light = 0;
                if (rippling) {
                    const s = this.field.sample(x, y);
                    i = s.from;
                    light = s.light;
                }
                let char = this.chars[i] ?? ' ';
                const base = this.share[i] ?? 0;
                let share = base;
                let colour = this.colours[i] ?? PAPER;
                const back = this.backs[i] ?? null;

                if (!screen) {
                    // The skin: slow currents shift each cell along the ramp and a
                    // little toward ink or paper, without touching its glyph.
                    if (living && base > 0) {
                        const drift = noise(x * 0.07 + now * 0.11, y * 0.14 - now * 0.07);
                        const depth = noise(x * 0.05 - now * 0.06 + 31, y * 0.1 + now * 0.05);
                        colour = rampAt(ramp, (this.tone[i] ?? 0) + (drift - 0.5) * 0.5);
                        const d = (depth - 0.5) * 0.7;
                        colour =
                            d > 0
                                ? mix(colour, paper ? INK_DEEP : CREAM, d)
                                : mix(colour, paper ? PAPER : ORCHID, -d * 0.6);
                    }
                    if (band && base > 0.04) {
                        const b = band(x, y);
                        if (b > 0.02) {
                            share = Math.min(1, share + 0.22 * b);
                            colour = mix(colour, paper ? CLOUD_TONE : CREAM, 0.6 * b);
                        }
                    }
                    if (touching && base > 0.03) {
                        const d = Math.hypot(x - touch.col, (y - touch.row) * 2) / TOUCH_RADIUS;
                        if (d < 2.2) {
                            const e = Math.exp(-d * d) * touch.presence;
                            share = Math.min(1, share + 0.2 * e);
                            colour = mix(colour, paper ? TOUCH_TONE : CREAM, 0.55 * e);
                        }
                    }
                    if (jetting) {
                        const ink = this.jetInk(x, y, now);
                        if (ink > 0.01) {
                            share = Math.max(share, ink * 0.97);
                            colour = mix(colour, paper ? INK_DEEP : CREAM, Math.min(1, ink * 1.15));
                        }
                    }
                    if (share !== base) char = pickChar(share, y, x, this.charset);
                }

                if (revealing && this.revealAt) {
                    const start = this.revealAt[at] ?? 0;
                    const local = (elapsed - start) / SOAK_MS;
                    if (local <= 0) continue;
                    if (local < 1 && share > 0) {
                        // Soaking in: the cell climbs the ramp from a blank to its
                        // glyph, its colour rising out of the ground.
                        const s = smooth(local);
                        char = pickChar(share * s, y, x, this.charset);
                        colour = mix(
                            screen ? BLACK : paper ? PAPER : ORCHID,
                            colour,
                            0.35 + 0.65 * s,
                        );
                    }
                }

                if (light !== 0) {
                    if (screen) {
                        colour = light > 0 ? mix(colour, WHITE, light) : mix(colour, BLACK, -light);
                    } else if (paper) {
                        colour =
                            light > 0
                                ? mix(colour, INK_DEEP, light * 0.7)
                                : mix(colour, PAPER, -light * 0.85);
                    } else {
                        colour =
                            light > 0
                                ? mix(colour, CREAM, light)
                                : mix(colour, ORCHID, -light * 0.85);
                    }
                }

                const px = x * w;
                const py = y * h;
                if (back) {
                    let bg = back;
                    if (light !== 0)
                        bg = light > 0 ? mix(bg, WHITE, light) : mix(bg, BLACK, -light);
                    ctx.fillStyle = css(bg);
                    lastFill = '';
                    ctx.fillRect(px, py, w + 0.5, h + 0.5);
                }
                if (char === ' ') continue;
                const fill = css(colour);
                if (fill !== lastFill) {
                    ctx.fillStyle = fill;
                    lastFill = fill;
                }
                ctx.fillText(char, px + w / 2, py + h / 2);
            }
        }
    }
}

/** Start a field when its plate first scrolls in, pause it while it is away. */
export function observeField(root: HTMLElement, field: InkField, onStart?: () => void): void {
    const live = (): void => {
        root.classList.add('is-live');
        onStart?.();
    };
    if (!('IntersectionObserver' in window)) {
        field.setVisible(true);
        field.start();
        live();
        return;
    }
    let started = false;
    let onScreen = false;
    const io = new IntersectionObserver(
        ([entry]) => {
            if (!entry) return;
            onScreen = entry.isIntersecting;
            if (onScreen && !started) {
                started = true;
                field.setVisible(true);
                field.start();
                live();
                return;
            }
            field.setVisible(onScreen);
        },
        { threshold: 0.15 },
    );
    io.observe(root);
    let width = 0;
    new ResizeObserver(([entry]) => {
        // Only a change of width relays the grid; a height change is our own.
        const next = Math.round(entry?.contentRect.width ?? 0);
        if (next === width) return;
        width = next;
        if (started) field.fit();
    }).observe(root);
    // A tab coming back resumes a field that is still on screen, no other.
    document.addEventListener('visibilitychange', () => field.setVisible(onScreen));
}
