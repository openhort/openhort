# Terminal Rendering

This note documents a terminal rendering bug that showed up in the web UI
with Claude Code's block-art avatar and line-drawing separators.

## Symptom

In the browser terminal:

- block-art characters had visible gaps or missing pixels
- some glyph parts appeared shifted inside the same character cell
- separator lines could grow small bogus symbols when overlap scaling was enabled

The same content rendered correctly in iTerm, so the PTY stream itself was not
the primary problem.

## Root Cause

The issue was in the bundled browser terminal renderer, not in Hort's PTY
transport and not in the terminal output timing.

OpenHORT had been bundling:

- `xterm.js 4.19.0`
- older matching addons

That older renderer stack misrendered some Unicode block-art / terminal-art
characters used by Claude Code. Local tweaks such as font size, line height,
or font family could change the appearance, but they did not remove the
underlying renderer bug.

## What Did Not Fix It

These changes were investigated and were not the real fix:

- changing `lineHeight`
- changing font family between `Menlo`, `SFMono-Regular`, and Courier stacks
- changing `fontSize`
- disabling `customGlyphs`
- enabling `rescaleOverlappingGlyphs` on the plain canvas renderer
- enabling Unicode 11 width handling

Some of these changed the symptom profile:

- `lineHeight` mainly changed row spacing
- font changes changed how squeezed or gappy the art looked
- `rescaleOverlappingGlyphs` on canvas reduced sprite seams but introduced
  artifacts on line-drawing characters

Those line artifacts appeared as small "clock"-like symbols on separator lines.

## Final Fix

The working fix was:

1. Upgrade the vendored terminal stack to a newer xterm release.
2. Use the matching WebGL addon for that newer version.
3. Enable overlap rescaling in the WebGL renderer path, not in the plain
   canvas renderer path.

The upgraded vendored versions are:

- `xterm.js 5.5.0`
- `xterm-addon-fit 0.10.0`
- `xterm-addon-web-links 0.11.0`
- `xterm-addon-webgl 0.18.0`

## Why This Worked

The old canvas renderer was the failing component for this class of glyphs.
The newer xterm release plus WebGL renderer handled the block-art characters
correctly. `rescaleOverlappingGlyphs` was only safe once it was applied in the
WebGL path; using it in the canvas path fixed one class of seams while
corrupting line-drawing characters.

Short version:

- old xterm canvas path: incorrect for this terminal art
- new xterm WebGL path: correct

## Current Configuration

The relevant frontend file is:

- `hort/static/index.html`

Important behavior:

- WebGL addon is loaded when available
- `rescaleOverlappingGlyphs` is enabled only after WebGL is active
- canvas remains the fallback path if WebGL cannot be created

## Contributor Guidance

If terminal art looks wrong again:

1. First suspect the bundled xterm version and renderer path.
2. Do not start with "timing" hypotheses unless there is evidence of
   asynchronous corruption.
3. Do not rely on `lineHeight` or font tweaks as a root fix.
4. Be careful with `rescaleOverlappingGlyphs` on canvas; it can introduce
   line-drawing artifacts.
5. Hard-reload the browser after changing vendored terminal assets, otherwise
   stale scripts can mask the real result.
