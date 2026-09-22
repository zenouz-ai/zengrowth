import type { Config } from 'tailwindcss'

// Tailwind reads the same CSS-variable design tokens defined in
// src/theme/tokens.css, so utilities and inline styles share one palette.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        border: 'var(--color-border)',
        text: 'var(--color-text)',
        muted: 'var(--color-muted)',
        cyan: 'var(--color-cyan)',
        emerald: 'var(--color-emerald)',
        loss: 'var(--color-loss)',
        warning: 'var(--color-warning)',
        violet: 'var(--color-violet)',
      },
      fontFamily: {
        heading: ['"Syne Variable"', 'Syne', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        body: ['"Outfit Variable"', 'Outfit', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono Variable"', '"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
