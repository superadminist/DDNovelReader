# Design QA

## Visual target

- Source set: `E:\ForCodex\dailyRepair\video-ui-extraction\WeChat_20260903141223\key-ui`
- Primary floating-window reference: `03_桌面悬浮朗读卡片.jpg`
- Requested direction: macOS desktop styling, preserving the supplied content-library, reader, playback, import, and floating-card patterns.

## Combined comparison

The local `/qa.html` view places the source floating-card screenshot and the rendered `/?qa=floating` prototype together in one viewport. It was inspected at the same time after the final responsive pass.

## Findings and fixes

1. The first responsive render was wider than the Codex in-app preview and clipped the content library. Fixed by adding a compact two-column library layout, a narrower rail, and reduced reading margins below 800 px.
2. The initial comparison iframe showed only part of the prototype. Fixed by scaling the full 650 px prototype viewport inside the comparison panel.
3. The floating card matches the reference hierarchy: quiet chapter label, centered context/current/next sentence, primary playback controls, compact utilities, rounded translucent surface, and soft shadow.
4. The floating card's initial position remains inside narrow viewports. A visible lower-right resize handle now drives explicit pointer-based width and height changes instead of relying on the browser's easy-to-miss native affordance. Title-bar dragging remains separate.
5. The reader keeps the reference structure: slim top toolbar, chapter directory, paper-like reading sheet, current-sentence highlight, and persistent bottom playback bar.

## Interaction checks

- Library search and book selection are available.
- `粘贴文本 → 加入并阅读` reaches the reader view.
- Reader chapter selection changes the active directory item.
- Font-size controls update the reading text.
- Playback toggles between play and pause and advances the visible progress value.
- Floating reader opens/closes, drags, resizes, plays/pauses, and switches the bilingual line on/off.

## Result

final result: passed

The prototype is visually aligned with the supplied macOS-style references and the core experience is interactive at both desktop and compact preview widths.
