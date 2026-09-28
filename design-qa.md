# ARGUS Mobbin-derived redesign QA

- Design reference: `C:\Users\gimye\Downloads\DESIGN-mobbin.md`
- Active contract: `C:\Users\gimye\Desktop\기타\프로젝트\ARGUS\DESIGN.md`
- Implementation screenshot: `C:\Users\gimye\Desktop\기타\프로젝트\ARGUS\design-implementation.png`
- Desktop viewport: 1380 × 900 CSS px
- Additional responsive inspection: Codex in-app browser at approximately 720px width
- State: idle, official results tab selected

## Applied direction

The interface now uses a gallery-white monochrome system: near-black ink, a short neutral tint ladder, shadow-free surfaces, stadium-pill controls, 24px major regions, and 16px fields. ARGUS-specific safety, live metrics, result separation, and evidence tables remain the content hierarchy.

Mobbin's marketing-scale display type, screenshot collages, commercial blue accent, imagery, and inverse footer were intentionally excluded because ARGUS is a desktop inspection console rather than a marketing site.

## Full-view evidence

The 1380 × 900 capture shows the complete primary workflow in one view: floating product/status pill, inspection launcher, five runtime metrics, current-work indicator, result tabs, result summary, and the table header. Vertical spacing was reduced after the first capture so the evidence workspace remains visible without losing the reference's whitespace-led grouping.

## Required fidelity surfaces

- Typography: system sans fallback with strong 700 headings, medium operational text, and lighter supporting copy. Declarative headings use sentence punctuation.
- Color: white, `#f3f3f3`, `#f0f0f0`, hairline grays, and near-black only in the idle screen. Restrained red is reserved for actual error/cancel/stop states.
- Shape: all buttons, tabs, counts, and status controls are full pills; fields use 16px corners; major operational and table surfaces use 24px corners.
- Elevation: no decorative drop shadows. Surface hierarchy uses fill differences and 1px hairlines. Only the modal retains an elevation shadow for modality.
- Layout: no nested dashboard-card grid. The launcher is open canvas, metrics share one operational surface, and all result views share one workspace.
- Content: all existing scan controls, live metrics, safety statement, official/auxiliary distinction, result fields, logs, and result-folder action remain.
- Accessibility: semantic tabs and panels, labeled input, live regions, keyboard result rows, visible ink focus ring, dialog semantics, and reduced-motion handling remain present.
- Responsive: the roughly 720px IAB view confirmed wrapped action controls, compact product pill, two-column metrics, and readable hierarchy without horizontal page overflow.

## Interaction and behavior boundaries

- DOM IDs consumed by `webui/app.js` are unchanged.
- pywebview API calls, polling, cancellation, folder opening, detail dialog, and safe-download behavior are unchanged.
- Progress remains indeterminate because the final URL count is not known during crawling.
- Detection and verifier thresholds were not modified.

## Findings

No actionable P0, P1, or P2 visual mismatch remains after the desktop spacing adjustment.

## Follow-up polish

- P3: confirm optical font weight once more in the packaged WebView2 window because Edge/WebView2 and headless Edge can rasterize Korean text slightly differently.

final result: passed
