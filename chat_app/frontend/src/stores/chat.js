import { defineStore } from 'pinia'
import {
  listSessions, createSession, deleteSession,
  getMessages, deleteMessage, uploadFile,
  chatOnce, chatStream,
} from '../api'

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessions: [],
    currentSessionId: null,
    messages: [],            // 当前会话消息列表
    streaming: false,        // 是否正在流式输出
    _abort: null,            // 当前流式请求的 abort 函数
    _assistantMsg: null,     // 正在累加的 assistant 消息引用
  }),

  actions: {
    async loadSessions() {
      this.sessions = await listSessions()
    },

    async selectSession(id) {
      if (this.currentSessionId === id) return
      this.currentSessionId = id
      this.messages = await getMessages(id)
    },

    async newSession() {
      // 流式输出中禁止切换/新建，避免数据错乱
      if (this.streaming) return
      this.currentSessionId = null
      this.messages = []
    },

    async removeSession(id) {
      if (this.streaming) return
      await deleteSession(id)
      if (this.currentSessionId === id) {
        this.currentSessionId = null
        this.messages = []
      }
      await this.loadSessions()
    },

    async removeMessage(id) {
      if (this.streaming) return
      const msg = this.messages.find(m => m.id === id)
      const realId = msg?._dbId || id
      await deleteMessage(realId)
      this.messages = this.messages.filter(m => m.id !== id)
    },

    async uploadAttachment(file) {
      return uploadFile(file) // {type,url,name,size}
    },

    /**
     * 发送消息（流式）。
     * @param {string} text
     * @param {Array<{type,url,name,size}>} attachments
     */
    async sendStream(text, attachments = []) {
      if (this.streaming || (!text && !attachments.length)) return

      // 若无 session，先创建（后端在第一次请求里也会建，但前端需要先有 id 用于 UI）
      let sessionId = this.currentSessionId
      if (!sessionId) {
        const sess = await createSession(text.slice(0, 30) || '新对话')
        sessionId = sess.id
        this.currentSessionId = sessionId
        await this.loadSessions()
      }

      // 1) 立刻渲染 user 消息
      const userMsg = {
        id: 'tmp-' + Date.now(),
        session_id: sessionId,
        role: 'user',
        content: text,
        attachments,
        created_at: new Date().toISOString(),
      }
      this.messages.push(userMsg)

      // 2) 占位 assistant 消息
      const asst = {
        id: 'tmp-asst-' + Date.now(),
        session_id: sessionId,
        role: 'assistant',
        content: '',
        attachments: null,
        created_at: new Date().toISOString(),
        streaming: true,
      }
      this.messages.push(asst)
      // 关键：从 reactive 数组中取回 proxy 引用，后续修改才能被 Vue 响应式系统检测到
      // 直接用原对象 asst 修改，Vue 无法追踪，导致 v-html / computed 不更新
      const reactiveAsst = this.messages[this.messages.length - 1]
      this._assistantMsg = reactiveAsst
      this.streaming = true

      const { abort, promise } = chatStream(
        { session_id: sessionId, message: text, attachments, stream: true },
        (evt) => this._handleSSE(evt, reactiveAsst, sessionId)
      )
      this._abort = abort
      try {
        await promise
      } finally {
        this.streaming = false
        this._abort = null
        if (reactiveAsst) reactiveAsst.streaming = false
      }
    },

    _handleSSE(evt, asst, sessionId) {
      console.log('[SSE]', evt.event, evt.data)
      switch (evt.event) {
        case 'meta':
          // 注意：不要修改 asst.id —— 它是 v-for 的 key，改了会导致组件销毁重建，流式数据丢失
          // 改为存入独立字段 _dbId
          asst._dbId = evt.data.message_id
          if (evt.data.session_id && !this.currentSessionId) {
            this.currentSessionId = evt.data.session_id
          }
          break
        case 'delta':
          // 保证响应式触发：用新字符串赋值而非 += 累加（Vue 对同一对象属性赋值有时不触发）
          asst.content = asst.content + evt.data.content
          break
        case 'done':
          asst.content = evt.data.content || asst.content
          asst.streaming = false
          // 流式完成后，把临时 id 替换为真实 id，保证后续操作（删除等）用正确的 id
          if (asst._dbId) {
            asst.id = asst._dbId
          }
          this.loadSessions()
          break
        case 'stopped':
          asst.streaming = false
          break
        case 'aborted':
          asst.streaming = false
          asst.content = asst.content + '\n\n_(已停止)_'
          break
        case 'error':
          asst.streaming = false
          asst.content = asst.content + `\n\n_(错误: ${evt.data?.message || '未知'})_`
          break
      }
    },

    stopStream() {
      if (this._abort) this._abort()
    },
  },
})
