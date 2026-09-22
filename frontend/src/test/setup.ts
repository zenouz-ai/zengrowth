import '@testing-library/jest-dom/vitest'

// Node 25 ships a built-in `localStorage` global that shadows jsdom's and is
// unusable without --localstorage-file, so tests calling `localStorage.clear()`
// fail on Node >= 25 while CI's pinned Node 24 passes. Install an in-memory
// Storage whenever the global is missing or unusable, so the suite is
// independent of the Node version.
function installMemoryStorage(key: 'localStorage' | 'sessionStorage'): void {
  try {
    const existing = (globalThis as Record<string, unknown>)[key] as Storage | undefined
    if (existing && typeof existing.clear === 'function' && typeof existing.setItem === 'function') {
      existing.setItem('__zg_probe__', '1')
      existing.removeItem('__zg_probe__')
      return
    }
  } catch {
    // fall through and install the in-memory replacement
  }

  const store = new Map<string, string>()
  const memory: Storage = {
    get length() {
      return store.size
    },
    clear: () => store.clear(),
    getItem: (name: string) => (store.has(name) ? (store.get(name) as string) : null),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (name: string) => void store.delete(name),
    setItem: (name: string, value: string) => void store.set(name, String(value)),
  }
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value: memory })
}

installMemoryStorage('localStorage')
installMemoryStorage('sessionStorage')
