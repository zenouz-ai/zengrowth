export const JD_CAPTURE_TYPE = 'zengrowth-jd'
export const JD_CAPTURE_ACK = 'zengrowth-jd-ack'
export const JD_CAPTURE_EVENT = 'zengrowth-jd-captured'
export const JD_CAPTURE_STORAGE_KEY = 'zengrowth-jd-capture'
export const JD_CAPTURE_TEXT_MAX = 50_000
export const JD_CAPTURE_QUERY_TEXT_MAX = 6_000
export const JD_CAPTURE_MIN_TEXT = 40

export type JdCapturePayload = { url: string; text: string }

export function parseJdCapture(data: unknown): JdCapturePayload | null {
  if (!data || typeof data !== 'object') return null
  const rec = data as Record<string, unknown>
  if (rec.type !== JD_CAPTURE_TYPE) return null
  const url = typeof rec.url === 'string' ? rec.url.trim().slice(0, 2000) : ''
  const text = typeof rec.text === 'string' ? rec.text.trim().slice(0, JD_CAPTURE_TEXT_MAX) : ''
  if (!url && text.length < JD_CAPTURE_MIN_TEXT) return null
  return { url, text }
}

export function stashJdCapture(payload: JdCapturePayload): void {
  try {
    sessionStorage.setItem(JD_CAPTURE_STORAGE_KEY, JSON.stringify(payload))
  } catch {
    /* private mode / quota */
  }
}

export function takeJdCapture(): JdCapturePayload | null {
  try {
    const raw = sessionStorage.getItem(JD_CAPTURE_STORAGE_KEY)
    if (!raw) return null
    sessionStorage.removeItem(JD_CAPTURE_STORAGE_KEY)
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return null
    return parseJdCapture({ type: JD_CAPTURE_TYPE, ...(parsed as object) })
  } catch {
    return null
  }
}

export function receiveJdCaptureMessage(data: unknown, ack?: () => void): JdCapturePayload | null {
  const payload = parseJdCapture(data)
  if (!payload) return null
  stashJdCapture(payload)
  ack?.()
  window.dispatchEvent(new CustomEvent(JD_CAPTURE_EVENT, { detail: payload }))
  return payload
}

/** Bookmarklet source. Runs on the posting page; opens /add and postMessages URL + text. */
export function buildBookmarklet(origin: string): string {
  const originLit = JSON.stringify(origin.replace(/\/$/, ''))
  return (
    'javascript:(function(){var O=' +
    originLit +
    ';var t=(window.getSelection&&String(getSelection()).trim())||(document.body&&document.body.innerText)||\'\';var w=window.open(O+\'/add\',\'zengrowth-jd\');if(!w){alert(\'Allow pop-ups to send this posting to ZenGrowth\');return;}var p={type:\'zengrowth-jd\',url:location.href,text:t.slice(0,50000)};var n=0;var i=setInterval(function(){n+=1;try{w.postMessage(p,O)}catch(e){}if(n>25)clearInterval(i)},200);function a(e){if(e.data&&e.data.type===\'zengrowth-jd-ack\'){clearInterval(i);window.removeEventListener(\'message\',a)}}window.addEventListener(\'message\',a)})();'
  )
}
