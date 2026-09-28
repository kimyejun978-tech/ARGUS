# ARGUS Product Design Contract

Status: active
Updated: 2026-09-23

## Source of truth

- Product behavior: `webui/index.html`, `webui/app.js`, and the desktop API contract.
- Visual system reference: user-supplied `DESIGN-mobbin.md`.
- ARGUS adopts the reference's monochrome gallery canvas, tint ladder, pill controls, and shadow-free geometry. It does not imitate Mobbin content, commercial screens, imagery, or branding.

## Brand

ARGUS is a precise, quiet inspection instrument. The interface should recede behind the scan target, live evidence, and result data. Identity is text-only: near-black wordmark, confident type, no decorative mark.

## Product goals

1. Make starting a URL or local-file inspection immediate.
2. Show live activity without a fabricated percentage.
3. Separate official findings from auxiliary diagnostics unmistakably.
4. Keep evidence tables dense, calm, and keyboard accessible.
5. State safe-download behavior without turning it into decoration.

## Personas and jobs

- Evaluator: understand and operate the tool without training.
- Site operator: start a scan, monitor it, and open exported results.
- Security reviewer: compare technique, evidence, URL, location, and auxiliary events.

## Information architecture

1. Floating product navigation pill: identity, safety statement, live status.
2. Inspection launcher: declarative heading, short guidance, URL/file input, actions.
3. Operations surface: five live metrics plus current target and indeterminate activity.
4. Results workspace: segmented official/auxiliary/log views and one dominant data surface.
5. Detail dialog for the selected row.

Avoid nested cards. Each major workflow receives at most one tinted surface; internal grouping uses whitespace and hairlines.

## Design principles

- Content first; chrome should nearly disappear.
- Monochrome by default. State color is semantic and rare.
- Use fill differences and 1px hairlines, never decorative shadows.
- All interactive controls use stadium-pill geometry.
- Headings are declarative Korean sentences ending in a period where natural.
- Preserve desktop efficiency: this is an operational tool, not a marketing page.

## Visual language

- Ink: `#141414`; soft ink: `#262626`.
- Canvas: `#ffffff`; soft canvas: `#f3f3f3`; field: `#f0f0f0`.
- Hairlines: `#e0e0e0` and `#f0f0f0`.
- Muted text: `#707070`; faint text: `#adadad`.
- Semantic exception: restrained red only for error/cancel/stop; technique types remain monochrome text chips.
- Local type stack: `Segoe UI`, `Malgun Gothic`, Arial, sans-serif. Use weights 700 for headings, 500 for body, 400 for supporting copy.
- Major surfaces use 24px radius; fields use 16px; controls and badges use full pills.
- No gradients, decorative blue, drop shadows, glass effects, illustrations, remote assets, or all-caps tracked eyebrows.

## Components

- Product pill: detached from window edge, soft-canvas fill, rounded full. Contains brand, safety copy, and status.
- Inspection launcher: open white space, centered copy, field row in `#f0f0f0`; focused field receives a 2px ink ring.
- Buttons: black primary pill, white outline secondary pill, soft stop pill.
- Operations surface: one `#f3f3f3` 24px container. Metrics are columns separated by hairlines, not individual cards.
- Progress: monochrome indeterminate bar while running; never a percentage.
- Tabs: segmented-control track in soft canvas with a white active pill.
- Result surface: soft-canvas table shell, hairline row separators, no outer shadow.
- Count badge: small monochrome pill.
- Technique label: compact outlined pill; text supplies the category.
- Auxiliary notice: neutral explanatory row; wording—not color—distinguishes non-official data.
- Dialog: white 24px surface with the only elevation shadow allowed for modality.

## Accessibility

- Preserve labels, live regions, tab relationships, dialog semantics, keyboard result activation, and disabled states.
- Visible 2px ink focus ring with sufficient contrast.
- Do not communicate status or risk through color alone.
- Meet WCAG AA for primary and supporting text.
- Respect reduced-motion preferences.

## Responsive behavior

- >= 1100px: single-line launcher, five metrics, full table.
- 720–1099px: input above an aligned action row; metrics wrap 3+2.
- < 720px: compact product pill, wrapped buttons, two-column metrics, horizontally scrollable tabs/table.

## Interaction states

- Idle: neutral status pill and disabled stop/folder actions.
- Running: ink status emphasis, disabled target/start/file, indeterminate activity, live URL.
- Complete: explicit text and enabled result-folder action.
- Error/cancelled: explicit copy and restrained semantic surface.
- Empty: plain explanatory copy inside the result surface.
- Poll/API failure: existing form message remains visible without blocking navigation.

## Content voice

Concise Korean, calm and direct. Avoid marketing language. Keep “공식 탐지 결과” and “보조 위험 진단” exact. Explicitly say auxiliary download observations are not official results and files are not saved or executed.

## Implementation constraints

- Preserve every DOM ID referenced by `webui/app.js` and every pywebview API behavior.
- No external font, icon, image, CDN, or new dependency.
- Do not modify detector/verifier logic or thresholds.
- Keep packaged WebView2 and browser preview visually equivalent.
- Never add file opening or execution behavior.

## Open questions

- If an original ARGUS symbol is created later, validate it independently; the current system intentionally uses a text wordmark.
- Perform a final optical check in packaged WebView2 because font rendering can differ from Chromium.
