# HAC-FEW Console design system

Direction: **Minimalism & Swiss, light-mode first**. 1 px rules instead of shadows, one navy primary, semantic risk colours,
IBM Plex Sans for interface text and JetBrains Mono for IDs, events, code, timings and technical data (both self-hosted via
`@fontsource`, OFL licensed). Tokens live in [`apps/console/src/styles/index.css`](../apps/console/src/styles/index.css).

## Tokens and measured contrast

Run `node apps/console/scripts/contrast.mjs` to reproduce. WCAG 2.x ratios:

| Token | Value | Use | Result |
|---|---|---|---|
| `ink` on canvas / surface | `#0F172A` | text | 17.1 / 17.9 : 1 |
| `ink-2` on canvas / surface | `#475569` | secondary text | 7.2 / 7.6 : 1 |
| white on `navy` | `#1E3A5F` | primary button | 11.5 : 1 |
| `link` on surface | `#2563EB` | links, focus ring | 5.2 : 1 (ring 4.9 : 1 on canvas) |
| `warn` on surface / tint | `#B45309` | medium risk, awaiting | 5.0 / 4.8 : 1 |
| `bad` on surface | `#DC2626` | graphics, high risk border | 4.8 : 1 |

**Approved tokens that did not pass as text, and what the system does instead**

| Approved | Problem | Used instead |
|---|---|---|
| Green `#16A34A` | 3.3 : 1 on white. Fails 4.5 : 1 as text | Text uses `ok-ink #15803D` (5.0 : 1). `#16A34A` is only used for graphics (borders, bars), where 3 : 1 applies |
| Red `#DC2626` on `#FEF2F2` | 4.4 : 1 | Text on red tint uses `bad-ink #B91C1C` (5.9 : 1) |
| Border `#CBD5E1` | 1.4 : 1. Fine for decorative dividers, too faint to identify a control | Dividers and card edges keep `#CBD5E1`; inputs, selects and buttons use `line-strong #64748B` (4.8 : 1 ≥ 3 : 1) |

## Rules the components follow

* **Colour is never the only signal.** Status and risk badges always pair colour with an icon and a text label. Agents are told apart by
  shape plus label: supervisor = hexagon, HR = circle, finance = square, IT = diamond, trigger = triangle.
* **Real data only.** No sample numbers or decorative charts. Empty states say what will appear and what to do. The Model usage area
  states plainly that the engine makes no model calls.
* **Permissions.** Controls the server will refuse are hidden or disabled with a reason, but the UI is only a hint; the server enforces.
* **Dragging has an alternative.** Palette items can be dragged, and also added by click/keyboard.
* **Motion.** Only the live-run pulse and spinners, all disabled under `prefers-reduced-motion`.
* **Focus.** Global 2 px `link` outline on `:focus-visible`; dialogs use Radix focus management; a skip link precedes the navigation.

## What was and was not verified

Verified: token contrast (script above); the Playwright journey (`npm run e2e`) drove sign-in, build, save, reload, run, the approval
gate, a second user approving, and the trace views with the pointer, with zero browser console errors; layouts were inspected
by screenshot at 1440 px and 390 px.

Not verified: any keyboard-only pass (focus styles and Radix dialog focus-trapping are implemented but were not exercised by a test),
a screen-reader pass (NVDA/VoiceOver), an automated axe/Lighthouse audit, keyboard wiring of edges in the node editor (React Flow's
connection handles are pointer-driven; adding steps and editing parameters use ordinary buttons and inputs), dark mode (intentionally
not shipped), and browsers other than Chromium.
