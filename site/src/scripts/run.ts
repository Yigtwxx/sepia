/* Replays the two windows (components/Run.astro): the prompt window types the
   request and turns its spinner, and when the reply lands the viewer draws the
   picture, as the real viewer does when the prompt window tells it a new PNG is
   ready. Under reduced motion, or without IntersectionObserver, both show their
   final state at once. The viewer answers the pointer with the viewer's own
   ripples (lib/ripple.ts) the whole time. */
import type { Frame, Span } from '../data/demo';
import type { Charset } from '../lib/ramps';
import { InkField, type PictureColours } from './ink-field';

interface RunData {
    frames: Frame[];
    pictures: Record<string, { cols: number; rows: number } & Record<Charset, string>>;
}

const colours = new Map<string, Promise<PictureColours>>();

/** A picture's cell colours, fetched once (public/art/<id>.json). */
export function pictureColours(id: string): Promise<PictureColours> {
    let pending = colours.get(id);
    if (!pending) {
        pending = fetch(`${import.meta.env.BASE_URL.replace(/\/$/, '')}/art/${id}.json`).then(
            (r) => {
                if (!r.ok) throw new Error(`art/${id}.json: ${r.status}`);
                return r.json() as Promise<PictureColours>;
            },
        );
        colours.set(id, pending);
    }
    return pending;
}

function spanEl(s: Span): HTMLSpanElement {
    const el = document.createElement('span');
    el.textContent = s.text;
    if (s.tone) el.dataset.tone = s.tone;
    return el;
}

function lineEl(spans: Span[], anchor?: string): HTMLDivElement {
    const line = document.createElement('div');
    line.className = 'tui__line';
    if (anchor) line.dataset.anchor = anchor;
    for (const s of spans) line.append(spanEl(s));
    return line;
}

class Viewer {
    private field: InkField | null = null;
    private current = '';

    constructor(
        private root: HTMLElement,
        private data: RunData,
    ) {
        const canvas = root.querySelector<HTMLCanvasElement>('[data-viewer-canvas]');
        const first = Object.values(data.pictures)[0];
        if (!canvas || !first) return;
        try {
            this.field = new InkField(canvas, {
                look: 'screen',
                text: '',
                cols: first.cols,
                rows: first.rows,
                ripples: window.matchMedia('(hover: hover)').matches,
            });
        } catch {
            return; // no canvas: the last picture stays as text
        }
        root.classList.add('is-live');
        const field = this.field;
        let width = 0;
        new ResizeObserver(([entry]) => {
            const next = Math.round(entry?.contentRect.width ?? 0);
            if (next === width) return;
            width = next;
            field.fit();
        }).observe(root);
        new IntersectionObserver(([entry]) =>
            field.setVisible(Boolean(entry?.isIntersecting)),
        ).observe(root);
    }

    idle(shown: boolean): void {
        this.root.querySelector('[data-viewer-idle]')?.classList.toggle('is-shown', shown);
    }

    clear(): void {
        this.current = '';
        this.field?.clear();
        this.idle(true);
    }

    async show(id: string, animate: boolean): Promise<void> {
        const picture = this.data.pictures[id];
        if (!this.field || !picture) return;
        this.current = id;
        const c = await pictureColours(id).catch(() => null);
        if (!c || this.current !== id) return;
        this.idle(false);
        this.field.setPicture(c, { classic: picture.classic, symbols: picture.symbols });
        // A redraw from the top, quick, the way a terminal repaints its screen.
        if (animate) this.field.revealFrom([0.5, -0.35], 650);
    }
}

class Player {
    private lines = new Map<string, HTMLElement>();
    private timer: number | null = null;
    private reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    private status: HTMLElement | null;

    constructor(
        private out: HTMLElement,
        private frames: Frame[],
        private viewer: Viewer,
        root: HTMLElement,
    ) {
        this.status = root.querySelector('[data-run-status]');
    }

    private land(frame: Frame, animate: boolean): void {
        if (frame.paint) {
            void this.viewer.show(frame.paint, animate);
            if (this.status) this.status.textContent = '●';
        }
    }

    private place(frame: Frame): void {
        const el = lineEl(frame.spans, frame.anchor);
        const prev = frame.id ? this.lines.get(frame.id) : undefined;
        if (prev) prev.replaceWith(el);
        else this.out.append(el);
        if (frame.id) this.lines.set(frame.id, el);
    }

    reset(): void {
        if (this.timer) window.clearTimeout(this.timer);
        this.timer = null;
        this.out.replaceChildren();
        this.lines.clear();
        this.viewer.clear();
        if (this.status) this.status.textContent = '○';
    }

    finish(): void {
        this.reset();
        let painted = '';
        for (const f of this.frames) {
            this.place(f);
            if (f.paint) painted = f.paint;
        }
        if (painted) {
            void this.viewer.show(painted, false);
            if (this.status) this.status.textContent = '●';
        }
    }

    play(): void {
        this.reset();
        if (this.reduced) {
            this.finish();
            return;
        }
        let i = 0;
        const step = (): void => {
            const frame = this.frames[i++];
            if (!frame) {
                this.timer = null;
                return;
            }
            if (frame.type) {
                // Type the last span character by character, the earlier spans at once.
                const head = frame.spans.slice(0, -1);
                const tail = frame.spans[frame.spans.length - 1];
                const line = lineEl(head, frame.anchor);
                const typed = spanEl({ text: '', tone: tail?.tone });
                line.append(typed);
                this.out.append(line);
                if (frame.id) this.lines.set(frame.id, line);
                const text = tail?.text ?? '';
                let c = 0;
                const tick = (): void => {
                    typed.textContent = text.slice(0, ++c);
                    if (c < text.length)
                        this.timer = window.setTimeout(tick, 40 + Math.random() * 55);
                    else this.timer = window.setTimeout(step, this.frames[i]?.wait ?? 0);
                };
                this.timer = window.setTimeout(tick, frame.wait);
                return;
            }
            this.place(frame);
            this.land(frame, true);
            this.timer = window.setTimeout(step, this.frames[i]?.wait ?? 0);
        };
        this.timer = window.setTimeout(step, this.frames[0]?.wait ?? 0);
    }
}

export function initRun(): void {
    for (const root of document.querySelectorAll<HTMLElement>('[data-run-windows]')) {
        const out = root.querySelector<HTMLElement>('[data-tui-out]');
        const raw = root.querySelector('[data-run-data]')?.textContent;
        const viewerRoot = root.querySelector<HTMLElement>('[data-viewer]');
        if (!out || !raw || !viewerRoot) continue;
        const data = JSON.parse(raw) as RunData;
        const viewer = new Viewer(viewerRoot, data);
        const player = new Player(out, data.frames, viewer, root);
        root.querySelector('[data-run-replay]')?.addEventListener('click', () => player.play());
        if (!('IntersectionObserver' in window)) {
            player.finish();
            continue;
        }
        viewer.clear();
        let started = false;
        const io = new IntersectionObserver(
            (entries) => {
                if (!entries.some((e) => e.isIntersecting) || started) return;
                started = true;
                player.play();
                io.disconnect();
            },
            { threshold: 0.3 },
        );
        io.observe(root);
    }
}
