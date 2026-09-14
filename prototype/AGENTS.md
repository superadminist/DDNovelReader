# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Confirmed design direction

- The React UI in this directory is the production Qt WebEngine frontend as well as the browser prototype; contract changes must update both Qt and demo transports and rebuild `dist/client`.
- Match the supplied `key-ui` screenshots as a macOS-style desktop reading experience.
- Include the content library, reading view, chapter directory, import-text dialog, playback bar, and bilingual floating reader.
- The floating reader must be movable and freely resizable from its lower-right corner.
- Use an explicit visible lower-right resize handle with pointer-drag behavior; do not rely only on the browser's subtle native resize affordance.
- Treat the floating reader as the primary product surface: preserve the current sentence first, progressively hide the previous and then next sentence when space is constrained, and never overlay the title, error, or controls on text.
- The floating reader uses direct body-area mouse-wheel font sizing (14–40 px), background-only opacity (0–100%), and an independently configurable readable text color.
- The main window minimizes to the system tray; the floating window remains independent and must not add a second taskbar button.
- Keep all built-in Edge neural voices and append every locally enumerated Windows SAPI voice in the settings center.
- Drive floating-reader lyrics from the shared audio-start event: keep the current sentence visually centered and use a short vertical slide/fade when the sentence changes; sentence completion alone must not advance the visible lyric.
- Warm the one existing speech controller for the bound reader position; preloading must never create a second playback controller or a second playback state.
- On Windows 10, keep the main Qt/WebEngine composition path opaque so native move and resize never expose a full transparent frame. Restore its 22px rounded region only after live resize settles; clear that region while resizing, and never apply a native region to the translucent floating window.
- Main-window normal state remains visibly rounded, while maximized and fullscreen states remain square and flush with the screen edge.
- Give the floating surface a fuller 30px anti-aliased radius with a two-pixel transparent inset so boundary pixels are not clipped; its configurable background opacity must remain independent from text and controls.
- Keep the floating reader content-only while the pointer is away: fully collapse the top title strip and bottom controls so they consume no space, then restore them on hover or keyboard focus. Pointer-less/touch environments keep the controls visible.
- In the normal 448x295 floating size, pointer-away state shows previous, current, and next sentences together; pointer-hover state shows the title and playback controls and may reduce the lyric to the current sentence to protect it from overlap.
- Make that pointer-driven display mode a persisted setting that defaults on. When it is off, keep the title, current sentence, and playback controls visible. Native Qt enter/leave events are authoritative so WebEngine cannot leave the hover state stuck after the pointer exits.
- Floating settings save independently per field. The color picker is always usable and selecting a color immediately enters custom mode; auto color remains explicit. The first body-wheel font change immediately disables and persists reader-font following, and Chromium scrollbars stay hidden without removing programmatic overflow.
- Use Windows-style minimize, maximize/restore, and close controls on the far right of the main 54px title bar; keep search and avatar immediately to their left and the app title visually centered. Minimize goes to the tray, maximize state changes the icon to restore, and blank-title-bar drag/double-click remains available. The persisted settings switch decides whether the close button exits or minimizes to tray; the tray menu's Exit action always exits.
- Keep modal overlays on Qt WebEngine's stable composition path: use a translucent solid scrim rather than a full-window `backdrop-filter`, which can disappear for single frames while the reader repaints.
- Keep software updates inside the settings center: automatically check the latest stable GitHub Release when enabled, allow manual checks and version skipping, download only the exact versioned Windows installer plus `SHA256SUMS.txt`, verify SHA256 before enabling installation, and never install silently without a user action.
- Edge continuation must keep the selected neural voice while audio is still being prepared: start ordered multi-sentence lookahead alongside the current-sentence prime, never duplicate an in-flight synthesis request, and never switch to SAPI merely because a healthy prefetch is pending. If Edge synthesis actually fails, a session may fall back once but must not flap between Edge and SAPI afterward.
