<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import { listDocs, uploadDoc, deleteDoc, usageSummary, chatStream } from './api/index.js'

// ===== markdown-it：最小配置 + try/catch（防渲染崩溃）=====
let md = null
try {
  md = new MarkdownIt({ html: false, breaks: true, linkify: true })
} catch { md = null }

function renderMd(text) {
  if (!text) return ''
  try {
    return md ? md.render(text) : escapeHtml(text)
  } catch {
    return escapeHtml(text)
  }
}
function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
}

// ===== 状态 =====
const docs = reactive([])
const selectedIds = reactive(new Set())
const messages = reactive([])     // {role:'user'|'assistant', content, citations?, usage?, streaming?}
const input = ref('')
const running = ref(false)
const mode = ref('qa')            // qa | code
const convId = ref(null)
const summary = reactive({ today: null, total: null })
const uploading = ref(false)
const dragOver = ref(false)       // 全页拖拽遮罩
const draggingDepth = ref(0)      // 子元素进出计数
const errorTip = ref('')
let streamHandle = null

const readyDocs = computed(() => docs.filter(d => d.status === 'ready'))
const hasSelection = computed(() => selectedIds.size > 0)

// ===== 文档库 =====
async function loadDocs() {
  try {
    const list = await listDocs()
    docs.length = 0
    docs.push(...list)
  } catch { /* ignore */ }
}
async function loadSummary() {
  try {
    const s = await usageSummary()
    summary.today = s.today
    summary.total = s.total
  } catch { /* ignore */ }
}

async function handleFiles(fileList) {
  for (const f of Array.from(fileList || [])) {
    uploading.value = true
    try {
      const r = await uploadDoc(f)
      await loadDocs()
      loadSummary()
      pushSystem(`文档《${r.name}》已入库：${r.chunks} 个切片，向量化消耗 ${r.embed_tokens} tokens ≈ ¥${r.embed_cost}`)
    } catch (e) {
      pushSystem(`上传失败：${e.response?.data?.detail || e.message}`, true)
    } finally {
      uploading.value = false
    }
  }
}
function toggleDoc(id) {
  if (selectedIds.has(id)) selectedIds.delete(id)
  else selectedIds.add(id)
}
async function removeDoc(id) {
  await deleteDoc(id).catch(() => {})
  selectedIds.delete(id)
  await loadDocs()
}

function pushSystem(text, isError = false) {
  messages.push({ role: 'system', content: text, error: isError })
  scrollChat()
}

// ===== 全页拖拽 =====
function onDragEnter(e) {
  e.preventDefault()
  draggingDepth.value++
  if (e.dataTransfer?.types?.includes('Files')) dragOver.value = true
}
function onDragLeave(e) {
  e.preventDefault()
  draggingDepth.value--
  if (draggingDepth.value <= 0) {
    draggingDepth.value = 0
    dragOver.value = false
  }
}
function onDropZone(e) {
  e.preventDefault()
  draggingDepth.value = 0
  dragOver.value = false
  handleFiles(e.dataTransfer?.files)
}

// ===== 对话 =====
function send() {
  const q = input.value.trim()
  if (!q || running.value) return
  input.value = ''
  running.value = true
  errorTip.value = ''

  messages.push({ role: 'user', content: q })
  const m = reactive({ role: 'assistant', content: '', citations: null, usage: null, streaming: true })
  messages.push(m)
  scrollChat()

  streamHandle = chatStream(
    { question: q, conversation_id: convId.value, doc_ids: [...selectedIds], mode: mode.value },
    (evt) => {
      const name = evt.event
      // 直接改 reactive 数组内对象保证 Vue proxy 感知
      if (name === 'meta') {
        convId.value = evt.data.conversation_id
      } else if (name === 'cite') {
        m.citations = evt.data
      } else if (name === 'delta') {
        m.content += evt.data.content
        scrollChat()
      } else if (name === 'done') {
        m.streaming = false
        if (evt.data.content) m.content = evt.data.content
        m.usage = evt.data.usage
        running.value = false
        loadSummary()
        streamHandle = null
      } else if (name === 'error') {
        m.streaming = false
        m.errorText = evt.data.message || '未知错误'
        running.value = false
        streamHandle = null
      } else if (name === 'stopped' || name === 'aborted') {
        m.streaming = false
        running.value = false
        streamHandle = null
      }
    },
  )
}
function stopGen() {
  streamHandle?.abort()
}
function newConversation() {
  convId.value = null
  messages.length = 0
  streamHandle?.abort()
  running.value = false
}
function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function scrollChat() {
  nextTick(() => {
    const el = document.querySelector('.chat-body')
    if (el) el.scrollTop = el.scrollHeight
  })
}

onMounted(() => {
  loadDocs()
  loadSummary()
})
</script>

<template>
  <div class="shell" @dragenter="onDragEnter" @dragleave="onDragLeave" @dragover.prevent>
    <!-- 背景光斑 -->
    <div class="glow g1"></div>
    <div class="glow g2"></div>
    <div class="glow g3"></div>

    <!-- ====== 顶栏 ====== -->
    <header class="topbar glass">
      <div class="brand">
        <span class="logo">🧩</span>
        <div>
          <h1>组件库智能顾问</h1>
          <p>Element Plus / Ant Design · 上传组件文档 · AI 答疑 + 示例代码</p>
        </div>
      </div>

      <div class="mode-seg">
        <button :class="{ active: mode === 'qa' }" @click="mode = 'qa'">💬 答疑模式</button>
        <button :class="{ active: mode === 'code' }" @click="mode = 'code'">⚡ 示例代码模式</button>
      </div>

      <div class="cost-chip" title="Token 成本预估（按阿里云牌价估算）">
        <span class="dot"></span>
        <template v-if="summary.total">
          今日 ¥{{ Number(summary.today.cost_total).toFixed(4) }} ·
          累计 ¥{{ Number(summary.total.cost_total).toFixed(4) }}
          （{{ summary.total.calls }} 次）
        </template>
        <span v-else>成本面板加载中…</span>
      </div>
    </header>

    <!-- ====== 主体三栏 ====== -->
    <main class="layout">
      <!-- 左栏：知识库 -->
      <aside class="side glass">
        <div class="side-head">
          <b>📁 组件文档库</b>
          <span class="count">{{ readyDocs.length }}</span>
        </div>

        <!-- 拖拽/点击上传区 -->
        <label
          class="dropzone"
          :class="{ busy: uploading }"
          for="docInput"
          @click="$refs.docInput.click()"
        >
          <input
            id="docInput"
            ref="docInput"
            type="file"
            accept=".md,.txt,.pdf,.docx,.html"
            hidden
            @change="(e) => { handleFiles(e.target.files); e.target.value = '' }"
          />
          <template v-if="uploading">
            <div class="spin"></div>正在解析入库…
          </template>
          <template v-else>
            <div class="dz-icon">⬆️</div>
            拖拽文档到此处 或 点击选择<br />
            <small>支持 md / txt / pdf / docx / html</small>
          </template>
        </label>

        <p v-if="errorTip" class="err-tip">{{ errorTip }}</p>

        <div class="doc-list">
          <div v-for="d in docs" :key="d.id" class="doc-item"
               :class="{ checked: selectedIds.has(d.id), bad: d.status !== 'ready' }"
               @click="d.status === 'ready' && toggleDoc(d.id)">
            <input type="checkbox" :checked="selectedIds.has(d.id)" disabled />
            <div class="doc-info">
              <div class="doc-name" :title="d.name">{{ d.name }}</div>
              <div class="doc-meta">
                {{ d.status === 'ready' ? `${d.chunk_count} 切片 · ¥${Number(d.embed_cost).toFixed(4)}` : d.status }}
              </div>
            </div>
            <button class="doc-del" title="删除" @click.stop="removeDoc(d.id)">✕</button>
          </div>
          <div v-if="!docs.length" class="empty-docs">还没有文档，先拖一份《组件文档》进来吧</div>
        </div>

        <div class="side-foot">
          <button class="btn ghost wide" @click="newConversation">🗑 开启新会话</button>
          <p class="hint">勾选文档后提问将基于其内容检索作答（RAG）；不选则仅用通用知识。</p>
        </div>
      </aside>

      <!-- 右栏：对话 -->
      <section class="chat glass">
        <div class="chat-body">
          <div v-if="!messages.length" class="welcome">
            <div class="w-logo">🧩</div>
            <h2>问点什么吧</h2>
            <p>示例：</p>
            <div class="chips">
              <button @click="() => { input = 'el-table 怎么自定义列内容？' }">el-table 自定义列内容怎么写？</button>
              <button @click="() => { input = 'ElMessageBox.confirm 的回调用法' }">ElMessageBox.confirm 怎么用？</button>
              <button @click="() => { input = '上传文件组件 el-upload 怎么限制类型和大小？' }">el-upload 如何限制类型与大小？</button>
            </div>
            <p class="tip">💡 先在左侧勾选已上传的文档，可获得更精准的回答</p>
          </div>

          <div v-for="(msg, i) in messages" :key="i" class="msg-row" :class="msg.role">
            <div v-if="msg.role === 'system'" class="sys-line" :class="{ err: msg.error }">{{ msg.content }}</div>
            <template v-else>
              <div class="avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
              <div class="bubble-col">
                <div class="bubble" :class="{ me: msg.role === 'user', blink: msg.streaming && !msg.errorText }">
                  <template v-if="msg.role === 'assistant'">
                    <div v-if="msg.citations && msg.citations.length" class="cite-box">
                      📎 引用 {{ msg.citations.length }} 个片段：
                      <details v-for="(c, ci) in msg.citations" :key="ci">
                        <summary>《{{ c.doc_name }}》 相似度 {{ c.score }}</summary>
                        <pre>{{ c.content }}</pre>
                      </details>
                    </div>
                    <div v-if="msg.content" class="md" v-html="renderMd(msg.content)"></div>
                    <span v-else-if="!msg.errorText">思考中…</span>
                    <div v-if="msg.errorText" class="gen-err">❌ {{ msg.errorText }}</div>
                  </template>
                  <template v-else>{{ msg.content }}</template>
                </div>
                <div v-if="msg.role === 'assistant' && msg.usage" class="usage-line">
                  本次 {{ msg.usage.prompt_tokens }}+{{ msg.usage.completion_tokens }} tokens ·
                  预估 ¥{{ Number(msg.usage.cost_total).toFixed(4) }}
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- 输入区 -->
        <footer class="composer">
          <textarea
            v-model="input"
            rows="1"
            placeholder="输入你的疑问，Enter 发送 / Shift+Enter 换行"
            @keydown="onKeydown"
          ></textarea>
          <button v-if="!running" class="btn primary" :disabled="!input.trim()" @click="send">发送 ➤</button>
          <button v-else class="btn danger" @click="stopGen">⏹ 停止</button>
        </footer>
      </section>
    </main>

    <!-- ====== 全页拖拽遮罩 ====== -->
    <transition name="fade">
      <div v-if="dragOver" class="drag-mask" @drop="onDropZone" @dragover.prevent @dragenter.prevent>
        <div class="drag-card">
          <div class="big-icon">📥</div>
          <h2>松手上传组件文档</h2>
          <p>支持 md / txt / pdf / docx / html，上传后自动切分向量入库</p>
        </div>
      </div>
    </transition>
  </div>
</template>
