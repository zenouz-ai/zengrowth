// Regenerates public/apple-touch-icon.png and the PWA icons from
// public/favicon.svg (rendered on the brand background, since iOS icons are
// full-bleed and iOS ignores SVG favicons for home-screen tiles).
//
// One-off usage:
//   npm i --no-save playwright-core
//   CHROMIUM=/path/to/chromium node scripts/generate-icons.mjs
import { chromium } from 'playwright-core'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const publicDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'public')
const svg = readFileSync(join(publicDir, 'favicon.svg'), 'utf8')

const pageHtml = (size, markScale) => `<!doctype html><html><head><style>
  * { margin: 0; padding: 0; }
  body { width: ${size}px; height: ${size}px; overflow: hidden; }
  .bg {
    width: 100%; height: 100%;
    display: flex; align-items: center; justify-content: center;
    background:
      radial-gradient(${size * 0.9}px ${size * 0.7}px at 22% 0%, rgba(99, 50, 255, 0.38), transparent 62%),
      radial-gradient(${size * 0.8}px ${size * 0.6}px at 100% 12%, rgba(0, 212, 255, 0.20), transparent 58%),
      radial-gradient(${size * 1.1}px ${size * 0.9}px at 50% 118%, rgba(99, 50, 255, 0.25), transparent 60%),
      linear-gradient(160deg, #0b0c18 0%, #06060a 55%, #0a0b14 100%);
  }
  .mark { width: ${Math.round(size * markScale)}px; filter: drop-shadow(0 ${size * 0.02}px ${size * 0.09}px rgba(99, 50, 255, 0.55)); }
  .mark svg { width: 100%; height: 100%; display: block; }
</style></head><body><div class="bg"><div class="mark">${svg}</div></div></body></html>`

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined })
const targets = [
  { file: 'apple-touch-icon.png', size: 180, scale: 0.56 },
  { file: 'icon-192.png', size: 192, scale: 0.56 },
  { file: 'icon-512.png', size: 512, scale: 0.56 },
  // Maskable variant keeps the mark inside the 80% safe zone.
  { file: 'icon-maskable-512.png', size: 512, scale: 0.46 },
]
for (const t of targets) {
  const page = await browser.newPage({ viewport: { width: t.size, height: t.size } })
  await page.setContent(pageHtml(t.size, t.scale))
  await page.waitForTimeout(150)
  writeFileSync(join(publicDir, t.file), await page.screenshot({ type: 'png' }))
  await page.close()
  console.log('wrote', t.file)
}
await browser.close()
