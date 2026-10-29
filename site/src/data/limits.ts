/* Where sepia stops today, as the README says it. */
export const limits: readonly { title: string; body: string }[] = [
    {
        title: 'No viewer on Linux.',
        body: 'sepia imports and passes its tests there, but the second window cannot be opened. Windows 10/11 and macOS only.',
    },
    {
        title: 'Terminal.app may miss the pointer.',
        body: 'Ripples need the terminal to report the mouse. *Windows Terminal and iTerm2* do; macOS Terminal.app may not.',
    },
    {
        title: 'The free tier runs out.',
        body: 'Cloudflare’s free tier is *10,000 neurons a day*, about 100 pictures, reset at 00:00 UTC. Once it is used up, sepia paints on your own GPU for the rest of the session; without the local model, it cannot paint until the reset.',
    },
    {
        title: 'The local model is large.',
        body: 'About *16 GB* to download and 3 GB of packages, and it holds about 5 GB of VRAM from the moment sepia opens until it closes.',
    },
    {
        title: 'It only makes pictures.',
        body: 'It is not a chat assistant. Every request starts a new picture, and `/add` is how you build on one.',
    },
];
