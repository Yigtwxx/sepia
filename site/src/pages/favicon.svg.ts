/* The favicon: the mark alone, outlines only, so a browser tab draws it without
   the page's fonts. The pale tile, as in the nav, with its characters thickened
   so they hold at sixteen pixels. scripts/favicon.mjs turns the built file into the PNG and ICO
   sizes. */
import type { APIRoute } from 'astro';
import { emblemSvg } from '../lib/emblem';

export const GET: APIRoute = () =>
    new Response(emblemSvg('f', '', 'paper', true), {
        headers: { 'Content-Type': 'image/svg+xml' },
    });
