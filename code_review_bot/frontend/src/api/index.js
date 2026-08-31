import axios from 'axios'

// API 基址：相对路径
// 本地 dev: vite proxy 转发 /api → http://39.96.63.42/review
// Vercel  : vercel.json rewrites 代理 /api/* → http://39.96.63.42/review/api/*
const API_BASE = '/api'

const http = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
})

// ========== 上传 ==========
export const uploadImage = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return http.post('/api/review/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

// ========== 历史 ==========
export const getHistory = () => http.get('/api/review/history').then(r => r.data)
export const getDetail = (id) => http.get(`/api/review/${id}`).then(r => r.data)
export const deleteRecord = (id) => http.delete(`/api/review/${id}`).then(r => r.data)

/**
 * 流式审查：fetch + ReadableStream + AbortController
 * 事件：meta/stage/thought/step_start/step_result/delta/done/stopped/error
 *
 * @param {{error_text:string, images:Array}} payload
 * @param {(evt:{event:string,data:any})=>void} onEvent
 * @returns {{abort:()=>void, promise:Promise<void>}}
 */
export function runReviewStream(payload, onEvent) {
  const controller = new AbortController()

  const promise = (async () => {
    let resp
    try {
      resp = await fetch(API_BASE + '/api/review/run', {
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
      // 关键：Windows 下 sse-starlette 发 CRLF，先归一化为 LF，
      // 否则 \n\n 分隔符检测失效（项目一验证过的坑）
      buffer = buffer.replace(/\r\n/g, '\n')

      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const evt = parseSSEBlock(block)
        if (evt) onEvent(evt)
      }
    }
    if (buffer.trim()) {
      const evt = parseSSEBlock(buffer)
      if (evt) onEvent(evt)
    }
  })()

  return { abort: () => controller.abort(), promise }
}

function parseSSEBlock(block) {
  let event = 'message'
  const dataLines = []
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
