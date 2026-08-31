import axios from 'axios'

// 运行时 API 基址：优先读 VITE_API_BASE（Vercel 构建时注入），否则回退到公网后端
// 本地 dev: vite proxy 转发到 http://39.96.63.42/chat  →  VITE_API_BASE 留空即可
// Vercel  : 必须设 VITE_API_BASE=http://39.96.63.42/chat  →  否则 Vite 静态替换为空
const API_BASE = import.meta.env.VITE_API_BASE || 'http://39.96.63.42/chat'

const http = axios.create({
  baseURL: API_BASE,
  timeout: 600000,
})

// ========== 历史/会话管理 ==========
export const listSessions = () => http.get('/api/sessions').then(r => r.data)
export const createSession = (title) => http.post('/api/sessions', null, { params: { title } }).then(r => r.data)
export const deleteSession = (id) => http.delete(`/api/sessions/${id}`).then(r => r.data)
export const getMessages = (sid) => http.get(`/api/sessions/${sid}/messages`).then(r => r.data)
export const deleteMessage = (id) => http.delete(`/api/sessions/messages/${id}`).then(r => r.data)

// ========== 上传 ==========
export const uploadFile = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return http.post('/api/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

// ========== 非流式聊天 ==========
export const chatOnce = (payload) => http.post('/api/chat', payload).then(r => r.data)

/**
 * 流式聊天：用 fetch + ReadableStream + AbortController
 * 通过 onEvent 回调把 meta/delta/done/stopped/error 事件抛给上层。
 *
 * @param {Object} payload  { session_id, message, attachments }
 * @param {(evt:{event:string,data:any})=>void} onEvent
 * @returns {{abort:()=>void,promise:Promise<void>}}
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
      if (e.name === 'AbortError') {
        onEvent({ event: 'aborted', data: {} })
        return
      }
      onEvent({ event: 'error', data: { message: String(e) } })
      return
    }
    if (!resp.ok) {
      const text = await resp.text().catch(() => '')
      onEvent({ event: 'error', data: { message: `HTTP ${resp.status} ${text}` } })
      return
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
        if (e.name === 'AbortError') {
          onEvent({ event: 'aborted', data: {} })
          break
        }
        onEvent({ event: 'error', data: { message: String(e) } })
        break
      }
      buffer += decoder.decode(chunk, { stream: true })
      // 关键修复：Windows 下 sse-starlette 发送 CRLF，必须先归一化为 LF
      // 否则 \n\n 分隔符检测会失效（\r\n\r\n 中不存在连续的 \n\n）
      buffer = buffer.replace(/\r\n/g, '\n')

      // SSE 事件以双换行分隔
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const evt = parseSSEBlock(block)
        if (evt) onEvent(evt)
      }
    }
    // 处理尾部残留
    if (buffer.trim()) {
      const evt = parseSSEBlock(buffer)
      if (evt) onEvent(evt)
    }
  })()

  return {
    abort: () => controller.abort(),
    promise,
  }
}

function parseSSEBlock(block) {
  let event = 'message'
  const dataLines = []
  // 行尾已归一化为 LF，直接 split 即可
  for (const line of block.split('\n')) {
    if (!line) continue
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!dataLines.length) return null
  let data
  const rawStr = dataLines.join('\n')
  try {
    data = JSON.parse(rawStr)
  } catch {
    data = rawStr
  }
  return { event, data }
}
