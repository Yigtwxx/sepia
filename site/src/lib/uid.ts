/* Ids for SVG definitions that a page may repeat (a gradient per logo): unique
   within a build, and the same on every build. */
let count = 0;

export function uid(prefix: string): string {
    count += 1;
    return `${prefix}-${count}`;
}
