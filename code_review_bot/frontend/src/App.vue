<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import {
  uploadImage,
  getHistory,
  getDetail,
  deleteRecord,
  runReviewStream,
} from './api/index.js'

// ===== markdown-it：最小配置 + try/catch（防 ESM 导入失败崩溃）=====
let md = null
try {
  md = new MarkdownIt({ html: false, breaks: true, linkify: true })
} catch { md = null }
function renderMd(text) {
  if (!text) return ''
  try {
    return md ? md.render(text) : String(text).replace(/\n/g, '<br>')
  } catch {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\n/g, '<br>')
  }
}

// ===== 状态 =====
const errorText = ref('')
const images = reactive([])          // [{url,name,size}]
const running = ref(false)
const stages = reactive([])          // 阶段提示 {message}
const steps = reactive([])           // Agent 轨迹 {type, tool?, args?, text?, output?}
const reportMd = ref('')
let streamHandle = null

// 历史
const showHistory = ref(false)
const historyList = reactive([])
const viewingDetail = ref(false)

const TOOL_META = {
  search_stackoverflow: { icon: '🔍', label: '搜索 StackOverflow' },
  get_stackoverflow_answer: { icon: '📖', label: '阅读高票回答' },
  run_python_code: { icon: '⚡', label: '执行 Python 代码' },
}
function toolMeta(t) {
  return TOOL_META[t] || { icon: '🔧', label: t }
}

const hasInput = computed(() => !!errorText.value.trim() || images.length > 0)

// ===== 图片上传 =====
async function handleFiles(fileList) {
  for (const f of fileList) {
    if (!f.type.startsWith('image/')) continue
    if (f.size > 20 * 1024 * 1024) continue
    try {
      const info = await uploadImage(f)
      images.push(info)
    } catch (e) {
      alert(`上传失败：${f.name}\n${e.response?.data?.detail || e.message}`)
    }
  }
}
function onPick(e) {
  handleFiles(Array.from(e.target.files || []))
  e.target.value = ''
}
function onDrop(e) {
  handleFiles(Array.from(e.dataTransfer?.files || []))
}
function removeImage(i) {
  images.splice(i, 1)
}

// ===== 运行审查 =====
async function startReview() {
  if (!hasInput.value || running.value) return
  running.value = true
  viewingDetail.value = false
  stages.length = 0
  steps.length = 0
  reportMd.value = ''

  streamHandle = runReviewStream(
    { error_text: errorText.value.trim(), images: [...images] },
    onEvent,
  )
  await streamHandle.promise.catch(() => {})
}

function onEvent(evt) {
  const { event, data } = evt
  if (event === 'meta') {
    /* 任务 id，可忽略 */
  } else if (event === 'stage') {
    stages.push({ message: data.message })
    scrollProgress()
  } else if (event === 'thought') {
    steps.push({ type: 'thought', text: data.text })
    scrollProgress()
  } else if (event === 'step_start') {
    steps.push({ type: 'tool', tool: data.tool, args: data.args, output: '', done: false })
    scrollProgress()
  } else if (event === 'step_result') {
    // 关键：直接改 reactive 数组中的对象，Vue proxy 才能检测到更新
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].type === 'tool' && steps[i].tool === data.tool && !steps[i].done) {
        steps[i].output = data.output
        steps[i].done = true
        break
      }
    }
    scrollProgress()
  } else if (event === 'delta') {
    reportMd.value += data.content
    scrollReport()
  } else if (event === 'done') {
    reportMd.value = data.report || reportMd.value
    running.value = false
    loadHistory()
  } else if (event === 'finalize') {
    running.value = false
    loadHistory()
  } else if (event === 'error') {
    running.value = false
    steps.push({ type: 'error', text: data.message || '未知错误' })
    loadHistory()
  } else if (event === 'stopped' || event === 'aborted') {
    running.value = false
    stages.push({ message: '任务已中止' })
  }
}

function stopReview() {
  if (streamHandle) streamHandle.abort()
}

function resetAll() {
  errorText.value = ''
  images.length = 0
  stages.length = 0
  steps.length = 0
  reportMd.value = ''
  viewingDetail.value = false
}

// ===== 历史记录 =====
async function loadHistory() {
  try {
    const list = await getHistory()
    historyList.length = 0
    historyList.push(...list)
  } catch { /* ignore */ }
}

async function openRecord(id) {
  try {
    const r = await getDetail(id)
    viewingDetail.value = true
    running.value = false
    errorText.value = r.input_text || ''
    images.length = 0
    images.push(...(r.images || []))
    stages.length = 0
    steps.length = 0
    steps.push(...(r.trace || []).map((t) => ({
      type: t.type === 'thought' ? 'thought'
        : t.type === 'step_start' ? 'tool' : 'tool_done',
      tool: t.tool,
      args: t.args,
      text: t.text,
      output: t.output || '',
      done: true,
    })))
    reportMd.value = r.report || ''
    showHistory.value = false
    nextTick(() => window.scrollTo({ top: document.body.scrollHeight }))
  } catch (e) {
    alert('加载详情失败：' + e.message)
  }
}

async function removeRecord(id) {
  if (!confirm('删除这条记录？')) return
  await deleteRecord(id).catch(() => {})
  loadHistory()
}

function fmtTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

function scrollProgress() {
  nextTick(() => {
    const el = document.querySelector('.progress-card')
    if (el) el.scrollTop = el.scrollHeight
  })
}
function scrollReport() {
  nextTick(() => {
    const el = document.querySelector('.report-card')
    if (el) el.scrollTop = el.scrollHeight
  })
}

onMounted(loadHistory)
</script>

<template>
  <div class="page">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="brand">
        <span class="logo">🤖</span>
        <div>
          <div class="title">自动化代码审查助手</div>
          <div class="subtitle">Agent · Function Calling · StackOverflow 联网调研 · 沙箱代码验证</div>
        </div>
      </div>
      <button class="icon-btn" @click="showHistory = true">🕘 历史记录</button>
    </header>

    <main class="main">
      <!-- 输入卡 -->
      <section class="card input-card">
        <h3>1 · 提交报错信息</h3>
        <textarea
          v-model="errorText"
          rows="5"
          placeholder="粘贴完整的报错信息（Traceback / 异常消息），也可以只上传报错截图…"
        ></textarea>

        <div
          class="upload-zone"
          @dragover.prevent
          @drop.prevent="onDrop"
          @click="$refs.fileInput.click()"
        >
          <input ref="fileInput" type="file" accept="image/*" multiple hidden @change="onPick" />
          <template v-if="images.length">
            <div v-for="(img, i) in images" :key="img.url" class="thumb-wrap" @click.stop>
              <img :src="img.url" alt="截图预览" />
              <button class="thumb-del" title="移除" @click="removeImage(i)">×</button>
              <div class="thumb-name">{{ img.name }}</div>
            </div>
            <div class="upload-more">＋ 继续添加</div>
          </template>
          <template v-else>
            <div class="upload-hint">📷 点击选择 或 拖拽报错截图到此处</div>
          </template>
        </div>

        <div class="actions">
          <button
            v-if="!running"
            class="btn btn-primary"
            :disabled="!hasInput"
            @click="startReview"
          >🚀 开始自动审查</button>
          <button v-else class="btn btn-danger" @click="stopReview">⏹ 停止</button>
          <span v-if="running" class="status-chip">Agent 工作中…</span>
          <button class="btn btn-ghost" style="margin-left:auto" @click="resetAll">清空</button>
        </div>
      </section>

      <!-- 过程时间线 -->
      <section v-if="stages.length || steps.length" class="card progress-card">
        <h3>2 · Agent 执行过程</h3>
        <div v-for="(s, i) in stages" :key="'s'+i" class="timeline-item stage">ℹ️ {{ s.message }}</div>

        <template v-for="(s, i) in steps" :key="'t'+i">
          <div v-if="s.type === 'thought'" class="timeline-item thought">
            <b>💭 思考</b>
            <div class="pre">{{ s.text }}</div>
          </div>

          <div v-else-if="s.type === 'tool' || s.type === 'tool_done'" class="timeline-item tool">
            <div class="tool-head">
              <span>{{ toolMeta(s.tool).icon }} {{ toolMeta(s.tool).label }}</span>
              <span v-if="!s.done" class="spinner"></span>
              <span v-else class="badge done">完成</span>
            </div>
            <details v-if="s.args && Object.keys(s.args).length">
              <summary>调用参数</summary>
              <pre class="pre">{{ JSON.stringify(s.args, null, 2) }}</pre>
            </details>
            <details v-if="s.output" open>
              <summary>执行结果</summary>
              <pre class="pre">{{ s.output }}</pre>
            </details>
          </div>

          <div v-else-if="s.type === 'error'" class="timeline-item err">❌ {{ s.text }}</div>
        </template>
      </section>

      <!-- 审查报告 -->
      <section v-if="reportMd" class="card report-card" :class="{ streaming: running }">
        <h3>3 · 审查报告</h3>
        <div class="md-content" v-html="renderMd(reportMd)"></div>
      </section>
    </main>

    <!-- 历史抽屉 -->
    <teleport to="body">
      <div v-if="showHistory" class="mask" @click.self="showHistory = false">
        <aside class="drawer">
          <div class="drawer-head">
            <b>历史审查记录</b>
            <button class="icon-btn dark" @click="showHistory = false">×</button>
          </div>
          <div v-if="!historyList.length" class="empty-tip">暂无记录</div>
          <div v-for="r in historyList" :key="r.id" class="history-item" @click="openRecord(r.id)">
            <div class="hi-top">
              <span class="badge" :class="r.status">{{ r.status }}</span>
              <span class="time">{{ fmtTime(r.created_at) }}</span>
              <button class="del" @click.stop="removeRecord(r.id)">删除</button>
            </div>
            <div class="hi-text">{{ (r.input_text || r.extracted_error || '(截图)').slice(0, 80) }}</div>
          </div>
        </aside>
      </div>
    </teleport>
  </div>
</template>
