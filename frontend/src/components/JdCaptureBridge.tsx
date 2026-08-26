import { useEffect } from 'react'
import { JD_CAPTURE_ACK, receiveJdCaptureMessage } from '../lib/jdCapture'

/** Always-on listener so a bookmarklet can deliver a JD while login or
 * session-check is still on screen. */
export function JdCaptureBridge() {
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      receiveJdCaptureMessage(event.data, () => {
        try {
          const source = event.source as Window | null
          source?.postMessage({ type: JD_CAPTURE_ACK }, event.origin)
        } catch {
          /* closed popup */
        }
      })
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])
  return null
}
