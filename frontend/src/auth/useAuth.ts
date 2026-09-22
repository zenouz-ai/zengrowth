import { useSyncExternalStore } from 'react'
import { authBridge } from '../lib/authBridge'

// Subscribe any component to the external auth store.
export function useAuthed(): boolean {
  return useSyncExternalStore(authBridge.subscribe, authBridge.getSnapshot)
}
