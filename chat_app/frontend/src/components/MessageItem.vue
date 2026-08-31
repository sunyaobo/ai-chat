<template>
  <div :class="['msg-row', message.role]">
    <div class="avatar" :class="message.role">
      {{ message.role === 'user' ? '我' : 'AI' }}
    </div>
    <div class="bubble">
      <!-- 附件预览 -->
      <div v-if="attachments.length" class="attachments">
        <template v-for="a in attachments" :key="a.url">
          <a v-if="a.type === 'image'" :href="a.url" target="_blank" class="att-img">
            <img :src="a.url" :alt="a.name" />
          </a>
          <a v-else :href="a.url" target="_blank" class="att-file">
            <el-icon><Document /></el-icon>
            <span class="att-name">{{ a.name }}</span>
          </a>
        </template>
      </div>

      <!-- 内容：assistant 渲染 markdown；user 渲染纯文本 -->
      <div v-if="message.role === 'assistant'" class="md-body" v-html="rendered"></div>
      <div v-else class="md-body"><span class="plain">{{ message.content }}</span></div>

      <!-- 工具条：仅 AI 消息显示复制/删除；用户消息不显示 -->
      <div class="toolbar" v-if="message.role === 'assistant' && !message.streaming">
        <el-button text size="small" @click="onCopy">复制</el-button>
        <el-button text size="small" type="danger" @click="$emit('delete')">删除</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'

const props = defineProps({
  message: { type: Object, required: true },
})
defineEmits(['delete'])

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const rendered = computed(() => {
  try {
    return md.render(props.message.content || '')
  } catch {
    return props.message.content || ''
  }
})

const attachments = computed(() => props.message.attachments || [])

async function onCopy() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}
</script>

<style scoped>
.msg-row {
  display: flex;
  margin-bottom: 24px;
  gap: 10px;
}
.msg-row.user { flex-direction: row-reverse; }
.avatar {
  width: 36px; height: 36px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: #fff; flex-shrink: 0;
}
.avatar.user { background: #3370ff; }
.avatar.assistant { background: #00b42a; }
.bubble {
  max-width: 78%;
  background: #fff;
  padding: 10px 14px;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  word-break: break-word;
}
.msg-row.user .bubble { background: #e8f0ff; }
.attachments {
  display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;
}
.att-img img {
  width: 120px; height: 120px; object-fit: cover; border-radius: 6px;
  border: 1px solid #e5e6eb; cursor: pointer;
}
.att-file {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 10px; background: #f5f7fa; border-radius: 6px;
  font-size: 13px; color: #3370ff; text-decoration: none;
}
.att-name { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toolbar {
  margin-top: 6px;
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}
.msg-row.user .toolbar { justify-content: flex-start; }
.plain { white-space: pre-wrap; }
</style>
