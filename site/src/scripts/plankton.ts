/* The water at the edges of the page: the margins either side of the text, on wide
   screens, as the sea a cuttlefish swims in. Three things live there, all drawn in
   characters, all on one canvas behind a mask that keeps the text column clear
   (layouts/Layout.astro):

   - marine snow: small glyphs drift up and sway, breathing up and down the ramp,
     nearer ones larger and quicker, each moved by the scroll at its own depth;
     the pointer lights the ones it passes, a flash of pink like bioluminescence;
   - a depth gauge in the left margin: a ruler of ticks that runs with the scroll
     and a reading at its middle, so going down the page is going down the water,
     pink near the surface and violet below;
   - bubbles in the right margin: columns of them rise from the bottom, swelling
     from a dot to an O as the pressure falls, and burst into a star before the
     top, or when the pointer reaches them.

   Under reduced motion, on narrow screens, or without a canvas, nothing is drawn. */

const GLYPHS = ['.', "'", ':', '·', '*', '+', '°', '~', 'o'];
const BREATH = ['.', ':', '*', ':', '.', "'"];
const COLOURS = ['#db2777', '#c026d3', '#9333ea', '#7c3aed', '#ec4899'];
const FRAME_MS = 1000 / 30;
const GLOW_RADIUS = 120; // px
const PER_AREA = 1 / 9500; // motes per px² of viewport
const PAGE_MAX = 72 * 16; // --page-max, px
const FONT = "'IBM Plex Mono', ui-monospace, monospace";

const TICK = 26; // px between gauge ticks
const METRES_PER_TICK = 2;
const GAUGE_SPEED = 0.6; // gauge travel per px of scroll

interface Mote {
    x: number;
    y: number;
    depth: number; // 0 far .. 1 near
    speed: number; // px per second, upward
    sway: number; // px amplitude
    phase: number;
    glyph: string;
    breathes: boolean;
    colour: string;
    glow: number; // 0..1, decays
}

interface Bubble {
    x: number;
    y: number;
    born: number;
    speed: number;
    phase: number;
    burstAt: number; // y where it bursts
    burst: number; // seconds since it burst, or -1
}

const mix = (a: [number, number, number], b: [number, number, number], t: number): string =>
    `rgb(${a.map((v, i) => Math.round(v + ((b[i] ?? v) - v) * t)).join(' ')})`;

export function initPlankton(): void {
    const canvas = document.querySelector<HTMLCanvasElement>('[data-plankton]');
    if (!canvas) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    // Only where the margins are wide enough to hold it (the same as the CSS).
    const wide = window.matchMedia('(min-width: 80rem)');

    let width = 0;
    let height = 0;
    let edge = 0; // margin width, px
    let motes: Mote[] = [];
    let bubbles: Bubble[] = [];
    let nextBubble = [0, 0.9];
    let frame = 0;
    let last = 0;
    let lastScroll = window.scrollY;
    let pointer: { x: number; y: number } | null = null;

    const spawn = (y?: number): Mote => {
        const depth = Math.random();
        return {
            x: Math.random() * width,
            y: y ?? Math.random() * height,
            depth,
            speed: 6 + depth * 16,
            sway: 4 + Math.random() * 10,
            phase: Math.random() * Math.PI * 2,
            glyph: GLYPHS[Math.floor(Math.random() * GLYPHS.length)] ?? '.',
            breathes: Math.random() < 0.45,
            colour: COLOURS[Math.floor(Math.random() * COLOURS.length)] ?? COLOURS[0]!,
            glow: 0,
        };
    };

    const fit = (): void => {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        width = window.innerWidth;
        height = window.innerHeight;
        edge = Math.max(0, (width - PAGE_MAX) / 2);
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const count = Math.round(width * height * PER_AREA);
        while (motes.length < count) motes.push(spawn());
        motes.length = count;
    };

    const drawMotes = (t: number, dt: number, scrolled: number): void => {
        for (const m of motes) {
            // Rise, sway, and move with the page by depth: near motes slip past
            // faster than far ones, so the margin has some water in it.
            m.y -= m.speed * dt + scrolled * (0.15 + m.depth * 0.5);
            if (m.y < -20) Object.assign(m, spawn(height + 10 + Math.random() * 30));
            else if (m.y > height + 40) Object.assign(m, spawn(-10 - Math.random() * 30));
            const x = m.x + Math.sin(t * (0.3 + m.depth * 0.4) + m.phase) * m.sway;
            if (pointer) {
                const d = Math.hypot(x - pointer.x, m.y - pointer.y);
                if (d < GLOW_RADIUS) m.glow = Math.max(m.glow, 1 - d / GLOW_RADIUS);
            }
            m.glow *= 0.94;
            let glyph = m.glyph;
            if (m.breathes) {
                const b = (Math.sin(t * 0.9 + m.phase * 3) + 1) / 2;
                glyph = BREATH[Math.floor(b * (BREATH.length - 1))] ?? glyph;
            }
            if (m.glow > 0.35) glyph = m.glow > 0.7 ? '@' : '*';
            const size = 10 + m.depth * 10 + m.glow * 6;
            ctx.globalAlpha = Math.min(1, 0.15 + m.depth * 0.25 + m.glow * 0.4);
            ctx.fillStyle = m.glow > 0.2 ? '#f0abfc' : m.colour;
            ctx.font = `500 ${size.toFixed(1)}px ${FONT}`;
            ctx.shadowBlur = m.glow > 0.2 ? 12 * m.glow : 0;
            ctx.shadowColor = 'rgba(236, 72, 153, 0.8)';
            ctx.fillText(glyph, x, m.y);
        }
        ctx.shadowBlur = 0;
    };

    const drawGauge = (scroll: number): void => {
        if (edge < 90) return;
        const x = edge * 0.42;
        const travel = scroll * GAUGE_SPEED;
        const first = Math.floor(travel / TICK);
        const offset = travel - first * TICK;
        const centre = height / 2;
        ctx.textBaseline = 'middle';
        for (let k = 0; ; k++) {
            const y = k * TICK - offset;
            if (y > height + TICK) break;
            const index = first + k;
            const metres = index * METRES_PER_TICK;
            // Fades toward the top and bottom of the window, darkens with depth.
            const fade = Math.max(0, 1 - Math.abs(y - centre) / (height * 0.55));
            const deep = Math.min(1, metres / 400);
            ctx.globalAlpha = 0.1 + 0.32 * fade;
            ctx.fillStyle = mix([219, 39, 119], [109, 40, 217], deep);
            const major = index % 5 === 0;
            ctx.textAlign = 'right';
            ctx.font = `500 ${major ? 13 : 11}px ${FONT}`;
            ctx.fillText(major ? '—+' : '-', x, y);
            if (major) {
                ctx.textAlign = 'left';
                ctx.font = `500 10.5px ${FONT}`;
                ctx.fillText(`${metres} m`, x + 6, y);
            }
        }
        // The reading, fixed at the middle of the window.
        const metres = ((travel + centre) / TICK) * METRES_PER_TICK;
        ctx.globalAlpha = 0.75;
        ctx.textAlign = 'right';
        ctx.fillStyle = mix([219, 39, 119], [109, 40, 217], Math.min(1, metres / 400));
        ctx.font = `500 15px ${FONT}`;
        ctx.fillText('›', x - 14, centre);
        ctx.textAlign = 'left';
        ctx.font = `500 12px ${FONT}`;
        ctx.fillText(`${metres.toFixed(1).padStart(5, '0')} m`, x + 6, centre);
        ctx.globalAlpha = 0.55;
        ctx.font = `500 9.5px ${FONT}`;
        ctx.fillText('DEPTH', x + 6, 84);
    };

    const drawBubbles = (t: number, dt: number): void => {
        if (edge < 90) return;
        const columns = [-0.18, 0.16].map((f) => width - edge / 2 + f * edge);
        columns.forEach((cx, i) => {
            if (t >= (nextBubble[i] ?? 0)) {
                bubbles.push({
                    x: cx,
                    y: height + 12,
                    born: t,
                    speed: 34 + Math.random() * 30,
                    phase: Math.random() * 6.3,
                    burstAt: height * (0.12 + Math.random() * 0.35),
                    burst: -1,
                });
                nextBubble[i] = t + 1.4 + Math.random() * 2.2;
            }
        });
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        bubbles = bubbles.filter((b) => b.burst < 0.35);
        for (const b of bubbles) {
            if (b.burst >= 0) {
                b.burst += dt;
            } else {
                b.y -= b.speed * dt;
                const near = pointer && Math.hypot(pointer.x - b.x, pointer.y - b.y) < 40;
                if (b.y <= b.burstAt || near) b.burst = 0;
            }
            // Swelling as it rises: the pressure on it falls.
            const rise = 1 - b.y / height;
            const x = b.x + Math.sin((t - b.born) * 2.2 + b.phase) * (3 + rise * 5);
            let glyph = rise < 0.3 ? '.' : rise < 0.55 ? 'o' : 'O';
            let size = 10 + rise * 9;
            let alpha = 0.18 + rise * 0.24;
            if (b.burst >= 0) {
                glyph = b.burst < 0.15 ? '*' : '·';
                size += 4;
                alpha *= 1 - b.burst / 0.35;
            }
            ctx.globalAlpha = Math.max(0, alpha);
            ctx.fillStyle = b.burst >= 0 ? '#f0abfc' : '#c026d3';
            ctx.font = `500 ${size.toFixed(1)}px ${FONT}`;
            ctx.fillText(glyph, x, b.y);
        }
    };

    const draw = (ms: number): void => {
        const dt = Math.min(0.1, (ms - last) / 1000);
        last = ms;
        const t = ms / 1000;
        const scroll = window.scrollY;
        const scrolled = scroll - lastScroll;
        lastScroll = scroll;
        ctx.clearRect(0, 0, width, height);
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        drawMotes(t, dt, scrolled);
        drawGauge(scroll);
        drawBubbles(t, dt);
        ctx.globalAlpha = 1;
    };

    const tick = (ms: number): void => {
        frame = 0;
        if (document.hidden || !wide.matches) return;
        if (ms - last >= FRAME_MS - 1) draw(ms);
        frame = requestAnimationFrame(tick);
    };
    const start = (): void => {
        if (!frame) frame = requestAnimationFrame(tick);
    };

    fit();
    last = performance.now();
    nextBubble = nextBubble.map((d) => last / 1000 + d);
    window.addEventListener('resize', fit);
    window.addEventListener(
        'pointermove',
        (event) => {
            if (event.pointerType === 'touch') return;
            pointer = { x: event.clientX, y: event.clientY };
        },
        { passive: true },
    );
    document.addEventListener('pointerleave', () => {
        pointer = null;
    });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            last = performance.now();
            start();
        }
    });
    wide.addEventListener('change', () => {
        if (wide.matches) {
            last = performance.now();
            start();
        }
    });
    canvas.classList.add('is-live');
    start();
}
