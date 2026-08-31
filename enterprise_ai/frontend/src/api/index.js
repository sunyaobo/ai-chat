import axios from 'axios'

// API 基址：空字符串，依赖代理处理
// 本地 dev: vite proxy 转发 /api → http://39.96.63.42/enterprise
// Vercel  : vercel.json rewrites 代理 /api/* → https://39.96.63.42/enterprise/api/*
const API_BASE = ''

const http = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
})

// ---------- 文档 ----------
export const listDocs = () => http.get('/api/docs').then(r => r.data)
export const uploadDoc = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return http.post('/api/docs/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
  }).then(r => r.data)
}
export const deleteDoc = (id) => http.delete(`/api/docs/${id}`).then(r => r.data)

// ---------- 成本 ----------
export const usageSummary = () => http.get('/api/chat/usage/summary').then(r => r.data)

// ---------- 会话 ----------
export const getMessages = (convId) =>
  http.get(`/api/chat/conversations/${convId}/messages`).then(r => r.data)

/**
 * 流式答疑 SSE（fetch + ReadableStream）
 * @returns {{abort:()=>void, promise:Promise<void>}}
 */
export function chatStream(payload, onEvent) {
  const controller = new AbortController()
  const promise = (async () => {
    let resp
    try {
      resp = await fetch(API_BASE + '/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
    } catch (e) {
      if (e.name === 'AbortError') return onEvent({ event: 'aborted', data: {} })
      return onEvent({ event: 'error', data: { message: String(e) } })
    }
    if (!resp.ok) {
      const t = await resp.text().catch(() => '')
      return onEvent({ event: 'error', data: { message: `HTTP ${resp.status} ${t}` } })
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    while (true) {
      let chunk
      try {
        const r = await reader.read()
        if (r.done) break
        chunk = r.value
      } catch (e) {
        if (e.name === 'AbortError') return onEvent({ event: 'aborted', data: {} })
        return onEvent({ event: 'error', data: { message: String(e) } })
      }
      buffer += decoder.decode(chunk, { stream: true })
      // Windows CRLF 归一化（sse-starlette 兼容坑）
      buffer = buffer.replace(/\r\n/g, '\n')
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const evt = parseSSE(block)
        if (evt) onEvent(evt)
      }
    }
    if (buffer.trim()) {
      const evt = parseSSE(buffer)
      if (evt) onEvent(evt)
    }
  })()
  return { abort: () => controller.abort(), promise }
}

function parseSSE(block) {
  let event = 'message'
  const datas = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) datas.push(line.slice(5).trimStart())
  }
  if (!datas.length) return null
  let data
  try {
    data = JSON.parse(datas.join('\n'))
  } catch {
    data = datas.join('\n')
  }
  return { event, data }
}
