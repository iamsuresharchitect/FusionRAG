// Relative path: Nginx routes /api/* to the backend (Step 16), so the
// same build works on localhost:3000 and on https://yourdomain.com.
export const API = import.meta.env.VITE_API_BASE || '/api'

async function handle(res) {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d) => d.error || d.msg || JSON.stringify(d)).join('; ')
        : detail
    } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return res.json()
}

export const getConfig = () => fetch(`${API}/config`).then(handle)
export const getDocuments = () => fetch(`${API}/documents`).then(handle)

export function uploadFiles(files, adminToken) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return fetch(`${API}/documents`, {
    method: 'POST',
    headers: adminToken ? { 'X-Admin-Token': adminToken } : {},
    body: form,
  }).then(handle)
}

export function deleteDocument(id, adminToken) {
  return fetch(`${API}/documents/${id}`, {
    method: 'DELETE',
    headers: adminToken ? { 'X-Admin-Token': adminToken } : {},
  }).then(handle)
}

// Streams Server-Sent Events from POST /chat.
export async function streamChat(payload, { onSources, onToken, onError, signal }) {
  const res = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!res.ok || !res.body) {
    await handle(res)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      const parsed = JSON.parse(data)
      if (event === 'sources') onSources?.(parsed)
      else if (event === 'token') onToken?.(parsed.text)
      else if (event === 'error') onError?.(parsed.message)
    }
  }
}
