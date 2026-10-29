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
        title: 'The free painter is weaker.',
        body: 'Without a key, Pollinations paints about *one picture per 15 seconds*, with a weaker model and a small logo, and ignores reference pictures.',
    },
    {
        title: 'The API cannot see the last picture.',
        body: 'An edit through the API repaints from the full prompt with the scene’s fixed seed, which keeps the shape close. Only the local model repaints *from the previous picture*.',
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
