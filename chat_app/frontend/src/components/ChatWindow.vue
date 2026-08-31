<template>
  <div class="chat-app">
    <!-- 左侧会话列表 -->
    <aside class="sidebar">
      <div class="sidebar-head">
        <span>对话</span>
        <el-button size="small" type="primary" plain :disabled="chat.streaming" @click="newChat">
          + 新建
        </el-button>
      </div>
      <ul class="session-list">
        <li
          v-for="s in chat.sessions"
          :key="s.id"
          :class="['session-item', { active: s.id === chat.currentSessionId }]"
          @click="chat.selectSession(s.id)"
        >
          <div class="session-info">
            <div class="session-title">{{ s.title || '新对话' }}</div>
            <div class="session-meta">
              <span v-if="s.message_count">{{ s.message_count }} 条</span>
              <span class="preview">{{ s.last_message || '暂无消息' }}</span>
            </div>
          </div>
          <el-icon class="del-icon" @click.stop="onDeleteSession(s.id)">
            <Delete />
          </el-icon>
        </li>
        <li v-if="!chat.sessions.length" class="empty">暂无会话</li>
      </ul>
    </aside>

    <!-- 主聊天区 -->
    <main class="main">
      <header class="main-head">
        <span class="title">
          {{ currentTitle || '新的对话' }}
        </span>
      </header>

      <div ref="scroller" class="message-area">
        <div v-if="!chat.messages.length" class="placeholder">
          发送文本、图片或文件开始对话
        </div>
        <MessageItem
          v-for="msg in chat.messages"
          :key="msg.id"
          :message="msg"
          @delete="onDelMessage(msg.id)"
        />
      </div>

      <MessageInput :disabled="chat.streaming" @send="onSend" @stop="chat.stopStream()" :streaming="chat.streaming" />
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useChatStore } from '../stores/chat'
import MessageItem from './MessageItem.vue'
import MessageInput from './MessageInput.vue'

const chat = useChatStore()
const scroller = ref(null)

const currentTitle = computed(() =>
  chat.sessions.find(s => s.id === chat.currentSessionId)?.title
)

chat.loadSessions()

watch(() => chat.messages.length, async () => {
  await nextTick()
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
})
// 流式输出过程中持续滚动
watch(() => chat.messages.map(m => m.content).join(''), async () => {
  await nextTick()
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
})

async function newChat() {
  await chat.newSession()
}

async function onDeleteSession(id) {
  try {
    await ElMessageBox.confirm('删除此会话？所有消息将一并删除。', '确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await chat.removeSession(id)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

async function onDelMessage(id) {
  await chat.removeMessage(id)
  ElMessage.success('已删除')
}

async function onSend({ text, attachments }) {
  await chat.sendStream(text, attachments)
}
</script>

<style scoped>
.chat-app {
  display: flex;
  height: 100%;
  width: 100%;
}
.sidebar {
  width: 280px;
  flex-shrink: 0;
  background: #ffffff;
  border-right: 1px solid #ebedf0;
  display: flex;
  flex-direction: column;
}
.sidebar-head {
  padding: 14px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 15px;
  border-bottom: 1px solid #f0f2f5;
}
.session-list {
  list-style: none;
  margin: 0;
  padding: 6px;
  flex: 1;
  overflow-y: auto;
}
.session-item {
  display: flex;
  align-items: center;
  padding: 10px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
}
.session-item:hover {
  background: #f5f7fa;
}
.session-item.active {
  background: #e8f0ff;
  color: #3370ff;
}
.session-info {
  flex: 1;
  min-width: 0;
}
.session-title {
  font-weight: 500;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  font-size: 12px;
  color: #8f959e;
  display: flex;
  gap: 8px;
  margin-top: 3px;
}
.session-meta .preview {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.del-icon {
  color: #c0c4cc;
  padding: 4px;
  border-radius: 4px;
  visibility: hidden;
}
.session-item:hover .del-icon { visibility: visible; }
.del-icon:hover { color: #f56c6c; background: #fef0f0; }

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  min-width: 0;
}
.main-head {
  padding: 14px 20px;
  background: #fff;
  border-bottom: 1px solid #ebedf0;
  font-weight: 600;
  font-size: 15px;
}
.message-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}
.placeholder {
  color: #8f959e;
  text-align: center;
  margin-top: 80px;
  font-size: 14px;
}
.empty { padding: 16px; text-align: center; color: #8f959e; font-size: 13px; }
</style>
