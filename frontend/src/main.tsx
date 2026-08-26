import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted brand fonts (bundled by Vite; no external requests at runtime).
import '@fontsource-variable/outfit/index.css'
import '@fontsource-variable/syne/index.css'
import '@fontsource-variable/jetbrains-mono/index.css'
import './theme/tokens.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
