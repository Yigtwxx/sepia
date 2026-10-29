/* The four movements of a request, from the README's "How it works". The ledger
   under each plate is this page's own run (scripts/spike.py --chain "pink and
   purple black hole" "a comet falling into it", saved in site/scripts/sources/):
   nothing here is made up. */
export interface Chapter {
    n: number;
    slug: string;
    verb: string;
    question: string;
    vignette: string;
    vignetteNote: string;
    plate: string;
    plateNumber: string;
    plateCaption: string;
    body: readonly string[];
    tagsLabel: string;
    tags: readonly string[];
    ledger: readonly { key: string; text: string; note?: string }[];
}

export const chapters: readonly Chapter[] = [
    {
        n: 1,
        slug: 'describe',
        verb: 'Describe',
        question: 'What do you want to see?',
        vignette: 'gosse',
        vignetteNote: 'Two words are enough. The art director does the rest.',
        plate: 'salviani',
        plateNumber: 'Pl. II',
        plateCaption: 'Ippolito Salviani, *Sepia*, 1554. The oldest plate on the page.',
        body: [
            'Type a few words in the prompt window: *a black hole*, *NYC nights*, a mood. Every request starts a new picture; `/add` builds on the one you have.',
            'Name a creature, a character or a landmark, or paste a link to a picture, and sepia paints from a *reference picture* instead of inventing a stranger. A bare name shows that picture as it is.',
        ],
        tagsLabel: 'say it as',
        tags: ['black hole', '/add a comet', 'yunara lol', 'a picture link'],
        ledger: [
            { key: 'REQUEST', text: 'pink and purple black hole' },
            { key: 'SCENE', text: 'empty', note: 'a new picture' },
            { key: 'THEN', text: '/add a comet falling into it', note: 'the same scene, built on' },
        ],
    },
    {
        n: 2,
        slug: 'direct',
        verb: 'Direct',
        question: 'Who decides what it looks like?',
        vignette: 'psm-bone',
        vignetteNote: 'The reply has a skeleton too: one fixed JSON schema.',
        plate: 'brehm',
        plateNumber: 'Pl. III',
        plateCaption:
            '*Common cuttlefish*, Brehms Tierleben, 1890. Two long arms, kept for the catch.',
        body: [
            'One Claude call per request. Claude, `claude-haiku-5-5` at high effort, is told to *look for an idea* before the first cliché, then writes a detailed English photo prompt made for symbol rendering: one dominant shape, strong light, saturated colour, no text.',
            'The same reply decides whether the request *edits the current picture* or starts a new one, and carries the one sentence the prompt window shows you.',
        ],
        tagsLabel: 'the reply',
        tags: ['message', 'prompt', 'edit', 'references'],
        ledger: [
            {
                key: 'MESSAGE',
                text: 'Painting a pink and violet black hole with a glowing lensed ring.',
            },
            {
                key: 'PROMPT',
                text: 'Cinematic astrophotography, wide telescope-style view of a supermassive black hole seen nearly edge-on…',
                note: '96 words',
            },
            { key: 'EDIT', text: 'false', note: 'then true, for /add a comet' },
            { key: 'TOKENS', text: '7,418 in · 972 out' },
        ],
    },
    {
        n: 3,
        slug: 'paint',
        verb: 'Paint',
        question: 'Who holds the brush?',
        vignette: 'eggs',
        vignetteNote: 'Painted at the viewer window’s own shape, so nothing is cut that matters.',
        plate: 'meyer',
        plateNumber: 'Pl. IV',
        plateCaption: 'Werner Th. Meyer, *Sepia officinalis*, 1913. The fin runs the whole mantle.',
        body: [
            'The prompt goes to *Cloudflare Workers AI* first, which runs *FLUX.2 [klein] 4B* on a free account. When the API fails or rate limits, sepia paints on your own GPU with the same model: CUDA first, then Apple Silicon, then the CPU. `/local` keeps it there.',
            'After a 429 it leaves Cloudflare alone for 120 seconds instead of asking again on every picture. Once the day’s free allocation is used up, it stops asking until `/api` or a restart, since a short wait does not bring it back.',
        ],
        tagsLabel: 'painters',
        tags: ['cloudflare', 'local GPU'],
        ledger: [
            { key: 'BLACK HOLE', text: 'local GPU · 4.0 s', note: '800 × 496' },
            { key: 'COMET', text: 'local GPU · 5.9 s', note: 'repainted from the first' },
            { key: 'SEED', text: 'fixed for the scene', note: 'so an edit keeps its shape' },
        ],
    },
    {
        n: 4,
        slug: 'ink',
        verb: 'Ink',
        question: 'How does a photo become text?',
        vignette: 'brehm-bone',
        vignetteNote: 'Thirty-one weights of character, from a blank to an @.',
        plate: 'psm',
        plateNumber: 'Pl. V',
        plateCaption:
            '*Cuttle-fish and shell*, Popular Science Monthly, 1889. Plain lines, every one kept.',
        body: [
            'The viewer stretches the contrast, boosts the colour and crops the picture to its window. Then every cell becomes *one character* whose ink covers as much of the cell as the light under it, from a ramp of 31 measured on the terminal’s own font.',
            'An ordered dither breaks smooth skies into mixed characters instead of bands, and each character takes the colour of its patch in 24-bit colour. A resize redraws it all, with no new API call.',
        ],
        tagsLabel: 'the ramp',
        tags: [' `\'-,_^"!<+?|c(i}nfoaXwbO%80WQ@'],
        ledger: [
            { key: 'GRID', text: '120 × 38 cells', note: 'this page’s viewer' },
            { key: 'CELL', text: '8 × 16 px', note: 'about twice as tall as wide' },
            { key: 'DITHER', text: '4 × 4 Bayer', note: 'strongest in the midtones' },
        ],
    },
];
