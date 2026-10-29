/* The install line, the commands and the links, as the README shows them. */
export interface Command {
    cmd: string;
    comment: string;
}

export const install: readonly { label: string; cmd: string }[] = [
    { label: 'uv', cmd: 'uv tool install sepia-cli' },
    { label: 'pipx', cmd: 'pipx install sepia-cli' },
    { label: 'pip', cmd: 'pip install sepia-cli' },
];

/* The prompt window's slash commands, word for word from src/sepia/ui.py. */
export const slashCommands: readonly Command[] = [
    { cmd: '/add <text>', comment: 'add to the current picture instead of starting a new one' },
    { cmd: '/clear', comment: 'clear the screen and start a fresh picture' },
    { cmd: '/style [ink|fill]', comment: 'choose how the picture is drawn' },
    { cmd: '/charset [classic|symbols]', comment: 'choose the characters that draw it' },
    { cmd: '/effort [low|medium|high|xhigh|max]', comment: 'choose how long Claude thinks' },
    { cmd: '/mature [on|off]', comment: 'allow sexy and dark pictures, never explicit' },
    { cmd: '/usage', comment: 'show what Claude and the image models used, now and in all' },
    { cmd: '/help', comment: 'show this list' },
    { cmd: '/exit', comment: 'close sepia and its window (also Ctrl+D)' },
];

/* The local painter: FLUX.2 [klein] 4B on your own GPU, from the README. */
export const localInstall: readonly { label: string; cmd: string; comment: string }[] = [
    {
        label: 'macOS',
        cmd: 'uv tool install "sepia-cli[local]"',
        comment: 'Apple Silicon: bf16 weights on MPS',
    },
    {
        label: 'Windows',
        cmd: 'uv tool install "sepia-cli[local]" --index https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match',
        comment: 'CUDA builds of torch come from the PyTorch index',
    },
];
export const download: Command = {
    cmd: 'sepia --download',
    comment: 'once: about 16 GB from Hugging Face',
};

/* Settings: the environment first, then .env here, then .env in the config folder. */
export const settings: readonly { name: string; value: string; what: string }[] = [
    {
        name: 'ANTHROPIC_API_KEY',
        value: 'asked on first run',
        what: 'the art director; the only key you need',
    },
    {
        name: 'POLLINATIONS_KEY',
        value: 'none',
        what: 'the keyed painter: no logo, paid from your pollen',
    },
    { name: 'BRAVE_SEARCH_API_KEY', value: 'none', what: 'named subjects from an image search' },
    { name: 'SEPIA_MODEL', value: 'claude-haiku-5-5', what: 'the art director model' },
    { name: 'SEPIA_EFFORT', value: 'high', what: 'how long Claude thinks per picture' },
    { name: 'SEPIA_STYLE', value: 'ink', what: 'ink or fill' },
    { name: 'SEPIA_CHARSET', value: 'classic', what: 'classic or symbols' },
];

export const version = '0.2.1';
export const repo = 'https://github.com/Yigtwxx/sepia';
export const pypi = 'https://pypi.org/project/sepia-cli/';

/* The sibling tools: same family, same page. */
export const siblings: readonly { name: string; href: string; tag: string }[] = [
    {
        name: 'proofpath',
        href: 'https://proofpath-yigtwx.vercel.app',
        tag: 'checks that a citation says what the claim says',
    },
    {
        name: 'spiyweb',
        href: 'https://spiyweb.vercel.app',
        tag: 'retrieval that spreads through a graph, not top-k',
    },
    {
        name: 'reasonhound',
        href: 'https://reasonhound.vercel.app',
        tag: 'a security scanner that follows the scent, not the checklist',
    },
];
