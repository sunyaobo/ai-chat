import axios from 'axios'

// API 基址：相对路径
// 本地 dev: vite proxy 转发 /api → http://39.96.63.42/qa
// Vercel  : vercel.json rewrites 代理 /api/* → http://39.96.63.42/qa/api/*
const API_BASE = '/api'

const http = axios.create({
  baseURL: API_BASE,
  timeout: 600000,
})

// ========== RAG 状态 ==========
export const getRagStatus = () => http.get('/api/qa/status').then(r => r.data)
export const rebuildIndex = () => http.post('/api/qa/rebuild').then(r => r.data)

// ========== 历史记录 ==========
export const getHistory = () => http.get('/api/qa/history').then(r => r.data)
export const deleteRecord = (id) => http.delete(`/api/qa/history/${id}`).then(r => r.data)
export const clearHistory = () => http.delete('/api/qa/history').then(r => r.data)

// ========== 非流式问答 ==========
export const askOnce = (question) =>
  http.post('/api/qa', { question, stream: false }).then(r => r.data)

/**
 * 流式问答：fetch + ReadableStream + AbortController
 * 通过 onEvent 回调把 meta/delta/done/stopped/error 事件抛给上层。
 *
 * @param {string} question
 * @param {(evt:{event:string,data:any})=>void} onEvent
 * @returns {{abort:()=>void,promise:Promise<void>}}
 */
export function askStream(question, onEvent) {
  const controller = new AbortController()

  const promise = (async () => {
    let resp
    try {
      resp = await fetch(API_BASE + '/api/qa/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, stream: true }),
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
