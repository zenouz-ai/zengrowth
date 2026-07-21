# ZenGrowth frontend

React 19 + TypeScript SPA built with Vite and Tailwind CSS. Served in production by
the multi-stage `web` image (Node build → nginx), which also proxies `/api` to the
FastAPI backend; in dev, Vite proxies `/api` (see `vite.config.ts`).

## Commands

```bash
npm ci            # install
npm run dev       # dev server with HMR + /api proxy
npm run build     # type-check (tsc -b) + production build
npm run lint      # eslint
npm test          # vitest (unit + render tests)
```

## Structure

- `src/pages/` — route-level views. All pages are code-split via `React.lazy` in
  `src/App.tsx`, so the entry chunk carries only the router/auth shell; recharts
  loads only with the pages that chart (Dashboard, Observability, PublicDashboard).
- `src/components/` — shared UI (glass `Panel`, `AlertBanner`, `Layout` chrome, …).
  `InterviewTimeline` + `JourneyRail` on Job detail drive the post-application interview
  workflow (rounds, prep packs, debriefs, simulator prompt).
- `src/auth/` + `src/lib/authBridge.ts` — session handling. `ProtectedRoute` resolves
  the session, then redirects unauthenticated visitors to `/login?next=…`. The axios
  interceptor in `src/lib/api.ts` flips the auth bridge on 401/403 so any component
  can react via `useSyncExternalStore`.
- `src/lib/api.ts` — the typed API client (same-origin `/api`, cookie auth).
- `src/theme/tokens.css` — dark-first brand tokens (colors as CSS variables).
  `tailwind.config.ts` maps utilities onto the same variables. Note: the token
  colors are plain `var()` strings, so Tailwind alpha modifiers (`bg-cyan/10`)
  don't apply real alpha — use explicit `rgba(...)` arbitrary values when opacity
  matters.

## Branding & icons

Brand fonts (Outfit for body, Syne for headings, JetBrains Mono for micro-labels)
are self-hosted via `@fontsource-variable` packages imported in `src/main.tsx` —
no external font requests at runtime.

`public/favicon.svg` is the in-app/browser-tab mark. iOS ignores SVG favicons for
home-screen tiles, so `public/apple-touch-icon.png` plus the PWA icons referenced by
`public/manifest.webmanifest` are pre-rendered PNGs of the mark on the brand
background. Regenerate them after changing the mark:

```bash
npm i --no-save playwright-core
CHROMIUM=/path/to/chromium node scripts/generate-icons.mjs
```

## Mobile notes

- `index.html` sets `viewport-fit=cover`; the `safe-px` / `safe-pb` utilities in
  `src/index.css` keep the sticky header and page bottom clear of the iPhone
  notch and home indicator.
- Form inputs use ≥16px text so iOS Safari doesn't auto-zoom on focus.
- Interactive targets in the header/menu are ≥44px tall.
