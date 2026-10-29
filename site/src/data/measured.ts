/* Numbers on the orchid band. Each one is in the README or in this page's own run
   (site/scripts/sources/*.json); the line under it says which. */
export interface Measure {
    figure: string;
    reading: string;
    what: string;
    source: string;
}

export const measures: readonly Measure[] = [
    {
        figure: '~$0.001',
        reading: 'per request',
        what: 'for the art director, Claude Haiku at the default effort',
        source: 'README, cost; plus $0.01 for each web search Claude makes',
    },
    {
        figure: '4.0',
        reading: 'seconds',
        what: 'to paint the black hole on this page, on a laptop GPU',
        source: 'this page’s run, FLUX.2 [klein] 4B; the README says about 3 s at 768 × 512',
    },
    {
        figure: '~5',
        reading: 'GB of VRAM',
        what: 'held by the local model, loaded in 4-bit on CUDA',
        source: 'README, painting backends',
    },
    {
        figure: '9,520',
        reading: 'characters',
        what: 'in the README’s waterfall, each chosen and coloured for the patch under it',
        source: 'README, the picture at the top',
    },
    {
        figure: '31',
        reading: 'weights of character',
        what: 'in the classic ramp; 15 in symbols, punctuation only',
        source: 'src/sepia/ascii_art.py',
    },
    {
        figure: '120',
        reading: 'seconds',
        what: 'that a rate-limited painter is left alone before sepia asks it again',
        source: 'README, painting backends',
    },
];

export const method = {
    title: 'where the numbers come from',
    lines: [
        'Costs: the README’s table, from list prices.',
        'Seconds: the metadata scripts/spike.py saved with this page’s two pictures.',
        'Characters and weights: the viewer’s own constants.',
    ],
};
