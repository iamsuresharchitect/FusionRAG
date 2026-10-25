import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { deleteDocument, getConfig, getDocuments, streamChat, uploadFiles } from './api.js'

const MODES = [
  { id: 'hybrid', label: 'Hybrid', hint: 'BM25 keywords + semantic vectors, fused with RRF' },
  { id: 'vector', label: 'Vector', hint: 'Semantic similarity only' },
  { id: 'keyword', label: 'Keyword', hint: 'BM25 exact-term matching only' },
]

const SUGGESTIONS = [
  'Summarise the key points of the uploaded documents',
  'What are the main steps described?',
  'List any error codes and how to fix them',
]

function readToken() {
  try { return localStorage.getItem('rag_admin_token') || '' } catch { return '' }
}
function saveToken(v) {
  try { localStorage.setItem('rag_admin_token', v) } catch { /* storage blocked */ }
}

function Sources({ sources }) {
  if (!sources?.length) return null
  return (
    <details className="sources">
      <summary>{sources.length} source{sources.length > 1 ? 's' : ''} retrieved</summary>
      <ol>
        {sources.map((s, i) => (
          <li key={s.id}>
            <div className="source-head">
              <span className="badge">[{i + 1}]</span>
              <strong>{s.doc_name}</strong>
              {s.page ? <span className="muted">p.{s.page}</span> : null}
            </div>
            <div className="scores">
              <span title="Reciprocal Rank Fusion score">RRF {s.score}</span>
              {s.vector_rank && <span title="Rank in semantic search">vec #{s.vector_rank} · {s.vector_score}</span>}
              {s.bm25_rank && <span title="Rank in keyword search">bm25 #{s.bm25_rank} · {s.bm25_score}</span>}
            </div>
            <p className="snippet">{s.text.length > 420 ? s.text.slice(0, 420) + '…' : s.text}</p>
          </li>
        ))}
      </ol>
    </details>
  )
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [docs, setDocs] = useState([])
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState('hybrid')
  const [topK, setTopK] = useState(6)
  const [adminToken, setAdminToken] = useState(readToken)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState(null) // {type, text}
  const [drawer, setDrawer] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const bottomRef = useRef(null)
  const fileRef = useRef(null)
  const abortRef = useRef(null)

  const refreshDocs = useCallback(() => {
    getDocuments().then(setDocs).catch((e) => setNotice({ type: 'error', text: `Backend unreachable: ${e.message}` }))
  }, [])

  useEffect(() => {
    getConfig().then((c) => { setConfig(c); setTopK(c.top_k || 6) }).catch(() => {})
    refreshDocs()
  }, [refreshDocs])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(t)
  }, [notice])

  async function handleFiles(fileList) {
    const files = Array.from(fileList || [])
    if (!files.length) return
    setUploading(true)
    try {
      const res = await uploadFiles(files, adminToken)
      const ok = res.added.map((d) => `${d.name} (${d.chunks} chunks)`).join(', ')
      const bad = res.errors.map((e) => `${e.file}: ${e.error}`).join('; ')
      setNotice({ type: bad ? 'warn' : 'ok', text: [ok && `Indexed ${ok}`, bad].filter(Boolean).join(' · ') })
      refreshDocs()
    } catch (e) {
      setNotice({ type: 'error', text: e.message })
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function handleDelete(doc) {
    if (!window.confirm(`Remove "${doc.name}" from the index?`)) return
    try {
      await deleteDocument(doc.id, adminToken)
      setNotice({ type: 'ok', text: `Removed ${doc.name}` })
      refreshDocs()
    } catch (e) {
      setNotice({ type: 'error', text: e.message })
    }
  }

  async function ask(question) {
    const q = question.trim()
    if (!q || busy) return
    const history = messages.map(({ role, content }) => ({ role, content }))
    setMessages((m) => [...m, { role: 'user', content: q }, { role: 'assistant', content: '', sources: [], pending: true }])
    setInput('')
    setBusy(true)
    const controller = new AbortController()
    abortRef.current = controller

    const patchLast = (fn) => setMessages((m) => {
      const copy = m.slice()
      copy[copy.length - 1] = fn(copy[copy.length - 1])
      return copy
    })

    try {
      await streamChat(
        { question: q, history, mode, top_k: topK },
        {
          signal: controller.signal,
          onSources: (sources) => patchLast((msg) => ({ ...msg, sources })),
          onToken: (t) => patchLast((msg) => ({ ...msg, content: msg.content + t, pending: false })),
          onError: (err) => patchLast((msg) => ({ ...msg, error: err, pending: false })),
        }
      )
    } catch (e) {
      if (e.name !== 'AbortError') patchLast((msg) => ({ ...msg, error: e.message }))
    } finally {
      patchLast((msg) => ({ ...msg, pending: false }))
      setBusy(false)
      abortRef.current = null
    }
  }

  const totalChunks = docs.reduce((n, d) => n + d.chunks, 0)

  return (
    <div className="app">
      <header className="topbar">
        <button className="icon-btn only-mobile" onClick={() => setDrawer(true)} aria-label="Open documents">☰</button>
        <div className="brand">
          <span className="logo">◮</span>
          <div>
            <h1>Hybrid RAG</h1>
            <p className="muted small">{config ? `${config.model} · ${config.embed_model}` : 'connecting…'}</p>
          </div>
        </div>
        <div className="modes" role="tablist" aria-label="Retrieval mode">
          {MODES.map((m) => (
            <button key={m.id} role="tab" aria-selected={mode === m.id}
              className={mode === m.id ? 'mode active' : 'mode'} title={m.hint} onClick={() => setMode(m.id)}>
              {m.label}
            </button>
          ))}
        </div>
      </header>

      <div className="layout">
        <aside className={drawer ? 'sidebar open' : 'sidebar'}>
          <div className="sidebar-head">
            <h2>Knowledge base</h2>
            <button className="icon-btn only-mobile" onClick={() => setDrawer(false)} aria-label="Close">✕</button>
          </div>

          <div
            className={dragOver ? 'dropzone over' : 'dropzone'}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files) }}
            onClick={() => fileRef.current?.click()}
            role="button" tabIndex={0}
          >
            <input ref={fileRef} type="file" multiple hidden
              accept={(config?.supported || ['pdf', 'docx', 'txt', 'md', 'csv']).map((e) => '.' + e).join(',')}
              onChange={(e) => handleFiles(e.target.files)} />
            {uploading ? <span className="spinner" /> : <span className="drop-icon">⇪</span>}
            <span>{uploading ? 'Indexing… (embedding chunks)' : 'Drop files or tap to upload'}</span>
            <span className="muted small">PDF, DOCX, TXT, MD, CSV · max {config?.max_upload_mb || 25} MB</span>
          </div>

          {config?.admin_required && (
            <label className="field">
              <span className="small muted">Admin token (needed to upload / delete)</span>
              <input type="password" value={adminToken} placeholder="paste ADMIN_TOKEN"
                onChange={(e) => { setAdminToken(e.target.value); saveToken(e.target.value) }} />
            </label>
          )}

          <div className="doc-stats small muted">{docs.length} documents · {totalChunks} chunks</div>
          <ul className="doc-list">
            {docs.map((d) => (
              <li key={d.id}>
                <span className="doc-icon">▤</span>
                <div className="doc-meta">
                  <span className="doc-name" title={d.name}>{d.name}</span>
                  <span className="small muted">{d.chunks} chunks{d.pages ? ` · ${d.pages} pages` : ''}</span>
                </div>
                <button className="icon-btn danger" onClick={() => handleDelete(d)} aria-label={`Delete ${d.name}`}>🗑</button>
              </li>
            ))}
            {!docs.length && <li className="empty small muted">No documents yet.</li>}
          </ul>

          <label className="field">
            <span className="small muted">Passages sent to Claude: <strong>{topK}</strong></span>
            <input type="range" min="2" max="12" value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
          </label>
          {config && !config.api_key_set && (
            <div className="notice warn small">ANTHROPIC_API_KEY is missing in backend/.env</div>
          )}
        </aside>
        {drawer && <div className="scrim only-mobile" onClick={() => setDrawer(false)} />}

        <main className="chat">
          <div className="messages">
            {!messages.length && (
              <div className="welcome">
                <h2>Ask your documents</h2>
                <p className="muted">Answers come from Claude, grounded in passages found by
                  {' '}<strong>{MODES.find((m) => m.id === mode).label.toLowerCase()}</strong> search, with numbered citations.</p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="chip" onClick={() => ask(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                {m.role === 'assistant' ? (
                  <>
                    {m.pending && !m.content ? <div className="typing"><span /><span /><span /></div> : (
                      <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>
                    )}
                    {m.error && <div className="notice error small">⚠ {m.error}</div>}
                    <Sources sources={m.sources} />
                  </>
                ) : <p>{m.content}</p>}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          <form className="composer" onSubmit={(e) => { e.preventDefault(); ask(input) }}>
            <textarea
              value={input} rows={1} placeholder="Ask a question about your documents…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(input) } }}
            />
            {busy ? (
              <button type="button" className="send stop" onClick={() => abortRef.current?.abort()}>Stop</button>
            ) : (
              <button type="submit" className="send" disabled={!input.trim()}>Send</button>
            )}
          </form>
          {messages.length > 0 && !busy && (
            <button className="link small" onClick={() => setMessages([])}>Clear conversation</button>
          )}
        </main>
      </div>

      {notice && <div className={`toast ${notice.type}`} onClick={() => setNotice(null)}>{notice.text}</div>}
    </div>
  )
}
