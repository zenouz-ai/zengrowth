// External auth store so any module (including the axios interceptor) can signal
// "the operator is no longer authenticated" without importing React. Components
// subscribe via useSyncExternalStore.

type Listener = () => void

let authed = true
const listeners = new Set<Listener>()

function emit() {
  for (const l of listeners) l()
}

export const authBridge = {
  subscribe(listener: Listener): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  getSnapshot(): boolean {
    return authed
  },
  setUnauthed(): void {
    if (authed) {
      authed = false
      emit()
    }
  },
  setAuthed(): void {
    if (!authed) {
      authed = true
      emit()
    }
  },
}
