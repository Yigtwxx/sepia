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
    { cmd: '/again', comment: 'paint the picture again with fresh noise, no new prompt' },
    { cmd: '/undo', comment: 'go back to the picture before' },
    { cmd: '/cam [off]', comment: 'show the webcam live; /cam again keeps the frame' },
    { cmd: '/clear', comment: 'clear the screen and start a fresh picture' },
    { cmd: '/style [ink|fill]', comment: 'choose how the picture is drawn' },
    { cmd: '/charset [classic|symbols]', comment: 'choose the characters that draw it' },
    { cmd: '/save', comment: 'save the picture in the window to Pictures/sepia' },
    { cmd: '/model [haiku|sonnet|opus|fable]', comment: 'choose which Claude writes the prompts' },
    { cmd: '/effort [low|medium|high|xhigh|max]', comment: 'choose how long Claude thinks' },
    {
        cmd: '/config',
        comment: 'turn clarifying questions, mature pictures and update notices on or off',
    },
    { cmd: '/mature [on|off]', comment: 'allow sexy and dark pictures, never explicit' },
    { cmd: '/api', comment: 'paint with Cloudflare, on this machine when it fails' },
    { cmd: '/local', comment: 'paint only on this machine’s GPU' },
    { cmd: '/keys [anthropic|cloudflare]', comment: 'set the keys sepia uses' },
    { cmd: '/usage', comment: 'show what Claude used and cost, now and in all' },
    { cmd: '/help', comment: 'show this list' },
    { cmd: '/exit', comment: 'close sepia and its window (also Ctrl+D, or Ctrl+C twice)' },
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
        what: 'the art director; the one key sepia needs',
    },
    {
        name: 'CLOUDFLARE_ACCOUNT_ID',
        value: 'none',
        what: 'the Cloudflare painter, together with the token',
    },
    {
        name: 'CLOUDFLARE_API_TOKEN',
        value: 'none',
        what: 'a free Workers AI token; without both, only the local model paints',
    },
    { name: 'BRAVE_SEARCH_API_KEY', value: 'none', what: 'named subjects from an image search' },
    { name: 'SEPIA_MODEL', value: 'claude-haiku-5-5', what: 'the art director model' },
    { name: 'SEPIA_EFFORT', value: 'high', what: 'how long Claude thinks per picture' },
    { name: 'SEPIA_STYLE', value: 'ink', what: 'ink or fill' },
    { name: 'SEPIA_CHARSET', value: 'classic', what: 'classic or symbols' },
    { name: 'SEPIA_MATURE', value: 'off', what: 'start with mature pictures on or off' },
    { name: 'SEPIA_ASK', value: 'on', what: 'let Claude ask about a vague request first' },
    { name: 'SEPIA_UPDATE_CHECK', value: 'on', what: 'say when a new sepia is out' },
];

export const version = '0.4.0';
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
