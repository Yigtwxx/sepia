# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions are written the PEP 440 way (`0.1.0a1`, not `0.1.0-alpha.1`), because
that is the string the wheel, PyPI and the release tag all carry.

## [Unreleased]

### Planned

Coming next. None of this is in a released version yet.

- The interactive prompt: run `sepia`, type a scene, and follow-up prompts
  edit the same picture.
- The viewer window: a second terminal window that shows only the picture,
  with no command line, title or header, redrawn in place on every prompt
  and on resize.

## [0.1.0a1] - 2026-10-28

The first alpha. It claims the `sepia-cli` name on PyPI with working code
rather than a placeholder: the drawing and rendering pipeline is in place,
while the interactive prompt and the viewer window are still to come (see
Unreleased).

### Added

- SVG rasterization through resvg. The drawing is scaled to cover the whole
  canvas and center-cropped, so it fills a terminal of any shape with no
  empty bars and no distortion.
- Image to colored symbols:
  - Cell colors are averaged in linear light, so thin bright details keep
    their real brightness instead of being darkened by sRGB averaging.
  - A symbol ramp ordered by each symbol's measured ink density.
  - Outlines from a thinned Sobel edge map, drawn with `/ \ | - _` along
    the direction of the edge.
  - A 4x4 Bayer dither on the midtones, faded out toward pure black and
    pure white so flat areas stay clean.
  - Two styles: `ink` colors the symbols on the terminal's own background
    (made for dark themes), and `fill` also paints each cell's background,
    which shows the picture on any theme.
- Scene drawing with Claude (`claude-opus-5-5`): a text prompt becomes an SVG
  scene, returned through structured output so the reply is a typed object
  rather than SVG scraped out of free text.

[Unreleased]: https://github.com/Yigtwxx/sepia/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/Yigtwxx/sepia/releases/tag/v0.1.0a1
