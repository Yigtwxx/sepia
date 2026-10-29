/* The two windows, replayed: `pink and purple black hole`, then `/add a comet
   falling into it`.

   This is the page's own run. scripts/spike.py made the same calls the prompt
   window makes (one Claude call, then the painter) and saved each picture with
   its reply, painter and time (site/scripts/sources/*.json); the lines below are
   what the prompt window prints for them, in its own words and colours
   (src/sepia/ui.py). A frame either appends a line or, when it names an `id`
   already on screen, replaces it: that is how the spinner turns and how the
   reply takes its place. A frame with `paint` tells the viewer to draw. */
import { pictures, type PictureArt } from './art.generated';
import { version } from './commands';

export type Tone = 'accent' | 'muted' | 'dim' | 'bold' | 'plain';

export interface Span {
    text: string;
    tone?: Tone;
}

export interface Frame {
    /** Milliseconds to wait before this frame lands. */
    wait: number;
    /** Lines with the same id replace each other. */
    id?: string;
    /** `type` frames are typed character by character. */
    type?: boolean;
    /** Where a field note beside the run may point (scripts/run-notes.ts). */
    anchor?: string;
    /** The viewer draws this picture when the frame lands. */
    paint?: string;
    spans: Span[];
}

/** SEPIA in the figlet font ANSI Shadow, as the prompt window opens with it. */
export const WORDMARK_BLOCK = '█';
export const wordmark: readonly string[] = [
    '███████╗███████╗██████╗ ██╗ █████╗ ',
    '██╔════╝██╔════╝██╔══██╗██║██╔══██╗',
    '███████╗█████╗  ██████╔╝██║███████║',
    '╚════██║██╔══╝  ██╔═══╝ ██║██╔══██║',
    '███████║███████╗██║     ██║██║  ██║',
    '╚══════╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝',
];
export const WORDMARK_COLUMNS = Math.max(...wordmark.map((line) => line.length));
/** ui.BANDS: letters banded pink to purple, left to right. */
export const WORDMARK_BANDS = ['#f9a8d4', '#f472b6', '#e879f9', '#c084fc', '#a78bfa'] as const;
/** ui.SHADOW: the shadow glyphs. */
export const WORDMARK_SHADOW = '#4c1d95';

export const welcome = {
    title: 'Welcome to sepia',
    version,
    tagline: 'draw with words',
    window: 'pictures open in a second window',
    help: '/help for commands',
    tip: ['Tip:', ' describe a scene, then build on it: "waterfall", "/add mountains"'] as const,
};

export const statusBar = `/help · haiku-5-5 (high) · ink/classic · ● window`;

const SPINNER = '✻✽✶✳✢·';
const TICK_MS = 100; // repl.py turns the spinner at about ten frames a second

/** The spinner turning on one line for `ms`, as repl.py's `_wait` draws it.
    `label` gets the request's running time (ui.elapsed): the spin begins `since`
    ms into the replay, and `scale` turns replay time into the run's time. */
function spin(
    id: string,
    label: (elapsed: string) => string,
    ms: number,
    { start = 0, since = 0, scale = 1 } = {},
): Frame[] {
    const frames: Frame[] = [];
    for (let t = 0; t < ms; t += TICK_MS) {
        const glyph = SPINNER[(start + t / TICK_MS) % SPINNER.length] ?? '✻';
        const seconds = Math.floor(((since + t) * scale) / 1000);
        frames.push({
            wait: frames.length === 0 ? 260 : TICK_MS,
            id,
            spans: [
                { text: ` ${glyph} `, tone: 'accent' },
                { text: label(`${seconds}s`), tone: 'muted' },
            ],
        });
    }
    return frames;
}

const blackhole = pictures.blackhole;
const comet = pictures.comet;
if (!blackhole || !comet) throw new Error('demo: run npm run images for the two pictures');

const PAINTER: Record<string, string> = {
    local: 'local GPU',
    api: 'cloudflare',
};

const WRITE_MS = 1700;
const PAINT_MS = 1400;

/** One request: echo, spinner while Claude writes, spinner while it paints, reply. */
function request(typed: string, anchor: string, pic: PictureArt, replyAnchor: string): Frame[] {
    const painter = PAINTER[pic.painter] ?? pic.painter;
    const spinner = `spin-${anchor}`;
    // The replay is quicker than the run; its counter keeps the run's pace, so
    // the painting spin lasts the picture's real seconds on it.
    const scale = (pic.seconds * 1000) / PAINT_MS;
    return [
        {
            wait: 900,
            type: true,
            anchor,
            spans: [
                { text: ' › ', tone: 'accent' },
                { text: typed, tone: 'plain' },
            ],
        },
        ...spin(spinner, (s) => `Working on it… (writing the prompt · ${s})`, WRITE_MS, {
            scale,
        }),
        ...spin(spinner, (s) => `Working on it… (painting · ${s})`, PAINT_MS, {
            start: 3,
            since: WRITE_MS,
            scale,
        }),
        {
            wait: 140,
            id: spinner,
            anchor: replyAnchor,
            paint: pic.id,
            spans: [
                { text: ' ⏺ ', tone: 'accent' },
                { text: pic.message, tone: 'plain' },
            ],
        },
        {
            wait: 60,
            anchor: `${replyAnchor}-end`,
            spans: [{ text: `   ${painter} · ${pic.seconds.toFixed(1)}s`, tone: 'muted' }],
        },
    ];
}

export const frames: readonly Frame[] = [
    ...request(blackhole.request, 'request', blackhole, 'reply'),
    ...request(`/add ${comet.request}`, 'add', comet, 'added'),
];

/** The margin notes, each pinned beside the lines it talks about. */
export const notes: readonly { id: string; text: string }[] = [
    {
        id: 'request',
        text: 'A few plain words. No lens, no light, no composition: the art director adds those.',
    },
    {
        id: 'reply',
        text: `Claude wrote a 96-word photo prompt; the GPU painted it in ${blackhole.seconds.toFixed(1)} s, and the window below drew it in characters.`,
    },
    {
        id: 'added',
        text: '/add keeps the scene and its seed. The prompt is rewritten whole, with a comet in it.',
    },
];
