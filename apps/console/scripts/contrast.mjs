// WCAG 2.x contrast check for design tokens. Run: node scripts/contrast.mjs
const lum = (hex) => {
  const c = hex.replace('#', '').match(/../g).map((h) => parseInt(h, 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
export const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}
const T = {
  canvas: '#F8FAFC', surface: '#FFFFFF', border: '#CBD5E1', text: '#0F172A', muted: '#475569',
  navy: '#1E3A5F', blue: '#2563EB', green: '#16A34A', amber: '#B45309', red: '#DC2626',
  greenText: '#15803D', greenTint: '#F0FDF4', amberTint: '#FFFBEB', redTint: '#FEF2F2', blueTint: '#EFF6FF',
  redText: '#B91C1C', controlBorder: '#64748B', navyTint: '#EEF2F7', mutedTint: '#F1F5F9', faint: '#64748B',
}
const checks = [
  ['text on canvas', T.text, T.canvas, 4.5], ['text on surface', T.text, T.surface, 4.5],
  ['muted on canvas', T.muted, T.canvas, 4.5], ['muted on surface', T.muted, T.surface, 4.5],
  ['faint on surface', T.faint, T.surface, 4.5],
  ['white on navy (primary button)', '#FFFFFF', T.navy, 4.5], ['white on blue', '#FFFFFF', T.blue, 4.5],
  ['blue link on surface', T.blue, T.surface, 4.5], ['blue on blue tint', T.blue, T.blueTint, 4.5],
  ['navy on navy tint', T.navy, T.navyTint, 4.5],
  ['GREEN #16A34A text on surface (proposed token)', T.green, T.surface, 4.5],
  ['green-text on surface', T.greenText, T.surface, 4.5], ['green-text on green tint', T.greenText, T.greenTint, 4.5],
  ['amber on surface', T.amber, T.surface, 4.5], ['amber on amber tint', T.amber, T.amberTint, 4.5],
  ['red on surface', T.red, T.surface, 4.5], ['red on red tint', T.red, T.redTint, 4.5],
  ['white on red (destructive button)', '#FFFFFF', T.red, 4.5],
  ['border on canvas (non-text 3:1)', T.border, T.canvas, 3], ['border on surface (non-text 3:1)', T.border, T.surface, 3],
  ['green #16A34A graphic on surface (3:1)', T.green, T.surface, 3], ['blue focus ring on canvas (3:1)', T.blue, T.canvas, 3],
  ['red-text on red tint', T.redText, T.redTint, 4.5], ['red-text on surface', T.redText, T.surface, 4.5],
  ['control border on surface (non-text 3:1)', T.controlBorder, T.surface, 3],
  ['control border on canvas (non-text 3:1)', T.controlBorder, T.canvas, 3],
  ['muted on muted-tint', T.muted, T.mutedTint, 4.5],
]
let fail = 0
for (const [name, fg, bg, min] of checks) {
  const r = ratio(fg, bg)
  const ok = r >= min
  if (!ok) fail++
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${r.toFixed(2).padStart(5)}:1  (need ${min})  ${name}`)
}
process.exit(0)
