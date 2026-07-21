// Shared Recharts theming so every chart reads the same way: muted axis ticks,
// a dark tooltip keyed to the design tokens, and a small set of semantic colours
// instead of one arbitrary accent. Use with <LabelList> to put values on bars so
// figures are legible without hovering (which is impossible on touch).

export const CHART_COLORS = {
  neutral: '#00d4ff', // cyan — neutral / accent
  positive: '#00ffa3', // emerald
  brand: '#6332ff', // violet
  warning: '#f7c948',
  negative: '#ff4466',
} as const

export const axisTick = { fill: '#8a93ad', fontSize: 11 } as const

export const tooltipStyle = {
  background: '#0d0e18',
  border: '1px solid #2a2d3a',
  borderRadius: 8,
  color: '#e8ecf5',
} as const

export const valueLabel = {
  fill: '#8a93ad',
  fontSize: 11,
  position: 'top' as const,
}
