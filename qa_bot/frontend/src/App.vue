<script setup>
import { ref, reactive, onMounted, nextTick, computed } from 'vue'
import MarkdownIt from 'markdown-it'
import {
  getHistory,
  askStream,
  clearHistory,
  getRagStatus,
} from './api/index.js'

// markdown-it：最小配置 + try/catch，避免 ESM 导入失败导致渲染崩溃
let md = null
try {
  md = new MarkdownIt({ html: false, breaks: true, linkify: true })
} catch (e) {
  console.warn('markdown-it 初始化失败，降级为纯文本', e)
  md = null
}
function renderMarkdown(text) {
  if (!text) return ''
  try {
    return md ? md.render(text) : escapeHtml(text)
  } catch (e) {
    return escapeHtml(text)
  }
}
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

// ===== 状态 =====
const messages = reactive([])      // {id, role, content, sources, loading}
const input = ref('')
const loading = ref(false)
const docCount = ref(0)
let streamHandle = null

// ===== 示例问题 =====
const examples = [
  '客户经理的考核指标有哪些？',
  '考核结果如何应用？',
  '客户经理的晋升条件是什么？',
]

// ===== 历史 =====
async function loadHistory() {
  try {
    const list = await getHistory()
    messages.length = 0
    for (const r of list) {
      messages.push({
        id: r.id,
        role: 'user',
        content: r.question,
        sources: null,
        loading: false,
      })
      messages.push({
        id: r.id,
        role: 'assistant',
        content: r.answer || '',
        sources: r.sources || null,
        loading: false,
      })
    }
    scrollToBottom()
  } catch (e) {
    console.error('加载历史失败', e)
  }
}

async function loadStatus() {
  try {
    const s = await getRagStatus()
    docCount.value = s.doc_count
  } catch (e) {
    /* 忽略 */
  }
}

// ===== 发送 =====
async function send(text) {
  const question = (text ?? input.value).trim()
  if (!question || loading.value) return

  input.value = ''
  loading.value = true

  // 用户消息
  messages.push({
    id: null,
    role: 'user',
    content: question,
    sources: null,
    loading: false,
  })
  // 助手占位（流式填充）
  const assistantMsg = reactive({
    id: null,
    role: 'assistant',
    content: '',
    sources: null,
    loading: true,
  })
  messages.push(assistantMsg)
  await scrollToBottom()

  // 流式
  streamHandle = askStream(question, (evt) => {
    if (evt.event === 'delta') {
      // 关键：直接修改 reactive 数组中的对象，确保 Vue proxy 检测到变化
      const msg = messages[messages.length - 1]
      if (msg && msg.role === 'assistant') {
        msg.content += evt.data.content
      }
      scrollToBottom()
    } else if (evt.event === 'done') {
      assistantMsg.loading = false
      assistantMsg.content = evt.data.content || assistantMsg.content
      assistantMsg.sources = evt.data.sources || null
      assistantMsg.id = evt.data.id
      loading.value = false
      streamHandle = null
      loadStatus()
    } else if (evt.event === 'error') {
      assistantMsg.loading = false
      assistantMsg.content = `[生成失败] ${evt.data.message || '未知错误'}`
      loading.value = false
      streamHandle = null
    } else if (evt.event === 'aborted' || evt.event === 'stopped') {
      assistantMsg.loading = false
      if (evt.data && evt.data.content) {
        assistantMsg.content = evt.data.content
      }
      loading.value = false
      streamHandle = null
    }
  })

  await streamHandle.promise.catch(() => {})
}

function stop() {
  if (streamHandle) streamHandle.abort()
}

async function clearAll() {
  if (!confirm('确认清空全部问答历史？')) return
  try {
    await clearHistory()
    messages.length = 0
  } catch (e) {
    alert('清空失败：' + e.message)
  }
}

function scrollToBottom() {
  return nextTick(() => {
    const el = document.querySelector('.chat-messages')
    if (el) el.scrollTop = el.scrollHeight
  })
}

function onKeydown(e) {
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

onMounted(() => {
  loadStatus()
  loadHistory()
})
</script>

<template>
  <div class="chat-layout">
    <!-- 顶栏 -->
    <header class="chat-header">
      <div>
        <div class="title">银行考核问答助手</div>
        <div class="subtitle">基于本地 Qwen2.5-7B-Instruct + RAG（{{ docCount }} 条知识切片）</div>
      </div>
      <div class="header-actions">
        <button class="icon-btn" @click="loadStatus" title="刷新状态">刷新</button>
        <button class="icon-btn" @click="clearAll" title="清空历史">清空</button>
      </div>
    </header>

    <!-- 消息区 -->
    <main class="chat-messages">
      <div v-if="messages.length === 0" class="empty-state">
        <div class="emoji">💬</div>
        <div class="hint">
          我是银行考核领域的问答助手，已学习《银行个金客户经理考核办法》。<br />
          试试问我下面的问题：
        </div>
        <div class="examples">
          <div
            v-for="q in examples"
            :key="q"
            class="example-item"
            @click="send(q)"
          >{{ q }}</div>
        </div>
      </div>

      <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
        <div class="avatar" :class="m.role">
          {{ m.role === 'user' ? '我' : 'AI' }}
        </div>
        <div class="msg-content">
          <div
            v-if="m.role === 'assistant'"
            class="bubble assistant"
            :class="{ 'cursor-blink': m.loading }"
          >
            <div
              v-if="m.content"
              class="md-content"
              v-html="renderMarkdown(m.content)"
            ></div>
            <span v-else-if="m.loading">正在思考</span>
          </div>
          <div v-else class="bubble user">{{ m.content }}</div>

          <!-- 来源引用 -->
          <div v-if="m.sources && m.sources.length" class="sources">
            <div class="sources-title">📎 参考资料（Top {{ m.sources.length }}）</div>
            <div
              v-for="(s, si) in m.sources"
              :key="si"
              class="source-item"
            >
              <div class="score">相似度: {{ s.score }}</div>
              <div class="text">{{ s.content }}</div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- 输入区 -->
    <footer class="chat-input">
      <div class="input-wrap">
        <textarea
          v-model="input"
          placeholder="输入你的问题，Enter 发送，Shift+Enter 换行"
          rows="1"
          @keydown="onKeydown"
        ></textarea>
        <button
          v-if="!loading"
          class="btn btn-primary"
          :disabled="!input.trim()"
          @click="send()"
        >发送</button>
        <button v-else class="btn btn-danger" @click="stop">停止</button>
      </div>
      <div class="input-hint">回答基于检索到的考核办法片段生成，仅供参考</div>
    </footer>
  </div>
</template>
