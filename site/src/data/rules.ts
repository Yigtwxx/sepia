/* Six things sepia will never do, each as the README and SECURITY.md state it. */
import type { IconName } from '../components/sketch/SketchIcon.astro';

export interface Rule {
    id: string;
    icon: IconName;
    title: string;
    body: string;
    margin: string;
}

export const rules: readonly Rule[] = [
    {
        id: 'words',
        icon: 'nopost',
        title: 'Send your words to the painter.',
        body: 'Cloudflare gets the English prompt Claude wrote, the picture size, the seed and, at most 512 px a side, the reference picture or the one you are adding to. *Your own request is not sent*, and nothing goes there at all when the picture is painted locally.',
        margin: 'The painter reads a prompt, never you.',
    },
    {
        id: 'home',
        icon: 'noglobe',
        title: 'Phone home.',
        body: 'There is *no telemetry*. Pictures, the request history and the key file stay in your user config folder, and the newest ten sessions are all it keeps.',
        margin: 'What it knows about you fits in one folder you can open.',
    },
    {
        id: 'key',
        icon: 'key',
        title: 'Write your key anywhere you did not put it.',
        body: 'Keys come from the environment or a `.env` file and are *never written to code, logs or error messages*. Asked on the first run, the key is typed hidden and saved to the config folder; on macOS that file is mode 600.',
        margin: 'Hidden as you type it, and after.',
    },
    {
        id: 'explicit',
        icon: 'shield',
        title: 'Paint something explicit.',
        body: 'Even with `/mature on`: no sex acts, no visible genitals, *no one who is or looks under 18*, no real person undressed. Such a request gets the nearest acceptable picture instead of a refusal.',
        margin: 'Dark and sexy, yes. Explicit, never.',
    },
    {
        id: 'settings',
        icon: 'window',
        title: 'Touch your terminal’s settings.',
        body: 'On Windows the viewer gets its own `sepia` profile, written as a Windows Terminal *fragment* in its own folder. Your `settings.json` is never opened; delete the folder and the profile is gone.',
        margin: 'A purple tab, and nothing changed behind it.',
    },
    {
        id: 'listen',
        icon: 'lock',
        title: 'Listen beyond this machine.',
        body: 'The two windows talk on `127.0.0.1` only. The viewer must pass an *HMAC challenge* with a fresh 32-byte key each session, and messages are JSON, never unpickled: a peer can send data, not code.',
        margin: 'Two windows, one loopback, one key a session.',
    },
];
