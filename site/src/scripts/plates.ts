/* Brings every character plate on the page to life (components/Inkprint.astro):
   its field of characters and, when it is framed, the skin round its frame. */
import { InkField, observeField } from './ink-field';
import { Skin, type SkinTones } from './skin';

export interface Plate {
    field: InkField;
    skin: Skin | null;
}

const plates = new WeakMap<Element, Plate>();

/** The live plate behind an `[data-ink-plate]` element, once it has one. */
export function plateFor(root: Element): Plate | undefined {
    return plates.get(root);
}

// Closed cells: pale pinks and lilacs; open ones darken to violet. On the orchid
// field the cells are plum at rest and open to the bands' pink.
const TONES: Record<'paper' | 'field', SkinTones> = {
    paper: {
        rest: [
            [240, 171, 212],
            [228, 168, 236],
            [200, 172, 246],
        ],
        open: [109, 40, 217],
    },
    field: {
        rest: [
            [140, 52, 132],
            [128, 58, 150],
            [112, 66, 170],
        ],
        open: [249, 168, 212],
    },
};
/** Inset of the skin's cells from the frame's outer edge, in px (Inkprint.astro). */
const SKIN_INSET = 7;

export function initPlates(): void {
    const hover = window.matchMedia('(hover: hover)').matches;
    for (const root of document.querySelectorAll<HTMLElement>('[data-ink-plate]')) {
        if (plates.has(root)) continue;
        const canvas = root.querySelector<HTMLCanvasElement>('[data-ink-canvas]');
        const text = root.querySelector<HTMLElement>('[data-ink-text]')?.textContent;
        if (!canvas || text == null) continue;
        const data = root.dataset;
        const look = data.look === 'field' ? 'field' : 'paper';
        const [ox = 0.5, oy = 0.45] = (data.origin ?? '').split(',').map(Number);
        const skinCanvas = root.querySelector<HTMLCanvasElement>('[data-skin]');
        let skin: Skin | null = null;
        if (skinCanvas) skin = new Skin(skinCanvas, () => SKIN_INSET, TONES[look]);

        let field: InkField;
        try {
            field = new InkField(canvas, {
                look,
                text,
                cols: Number(data.cols),
                rows: Number(data.rows),
                origin: [ox, oy],
                reveal: 'inkReveal' in data,
                ripples: hover && 'ripples' in data,
                jets: 'jets' in data,
                clouds: 'clouds' in data,
                // The hero's frame flushes from the head as each cloud starts.
                onCloud: () => skin?.flush(0.5, 0),
            });
        } catch {
            continue; // no canvas support: the <pre> stays
        }
        plates.set(root, { field, skin });
        observeField(root, field, () => {
            skin?.fit();
            skin?.flush(ox, oy < 0.5 ? 0 : 1);
        });
        if (skin) {
            new ResizeObserver(() => skin.fit()).observe(root);
            if (hover) {
                root.addEventListener('pointerenter', (event) => {
                    const box = root.getBoundingClientRect();
                    skin.flush(
                        (event.clientX - box.left) / box.width,
                        (event.clientY - box.top) / box.height,
                    );
                });
            }
        }
    }
}
