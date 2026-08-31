<template>
  <div class="input-area">
    <!-- 待发送附件预览 -->
    <div v-if="pending.length" class="pending-atts">
      <div v-for="(a, i) in pending" :key="a.url" class="pending-item">
        <img v-if="a.type === 'image'" :src="a.url" />
        <span v-else class="file-icon">📄</span>
        <span class="name">{{ a.name }}</span>
        <el-icon class="remove" @click="pending.splice(i, 1)"><CircleClose /></el-icon>
      </div>
    </div>

    <div class="input-row">
      <el-upload
        :show-file-list="false"
        :before-upload="handleUpload"
        multiple
        :disabled="uploading || streaming"
      >
        <el-button :icon="Plus" circle :disabled="streaming" title="上传图片/文件" />
      </el-upload>

      <textarea
        ref="ta"
        v-model="text"
        class="textarea"
        :placeholder="placeholder"
        :disabled="streaming"
        @keydown.enter.exact.prevent="onEnter"
        @input="autoGrow"
      />

      <el-button
        v-if="!streaming"
        type="primary"
        :icon="Position"
        :disabled="disabled || (!text.trim() && !pending.length)"
        @click="onSend"
      >发送</el-button>
      <el-button
        v-else
        type="danger"
        :icon="VideoPause"
        @click="$emit('stop')"
      >停止</el-button>
    </div>

    <div class="tip">Enter 发送，Shift+Enter 换行；图片/文件先上传再发送。</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Plus, Position, VideoPause, CircleClose } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '../stores/chat'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  streaming: { type: Boolean, default: false },
})
const emit = defineEmits(['send', 'stop'])

const chat = useChatStore()
const text = ref('')
const pending = ref([])
const uploading = ref(false)
const ta = ref(null)

const placeholder = '输入消息，可附图/文件…'

async function handleUpload(file) {
  uploading.value = true
  try {
    const att = await chat.uploadAttachment(file)
    pending.value.push(att)
  } catch (e) {
    ElMessage.error('上传失败：' + (e?.message || String(e)))
  } finally {
    uploading.value = false
  }
  return false // 阻止 el-upload 默认上传
}

function onEnter() {
  if (props.streaming) return
  onSend()
}

function onSend() {
  if (props.disabled) return
  const t = text.value.trim()
  if (!t && !pending.value.length) return
  emit('send', { text: t, attachments: [...pending.value] })
  text.value = ''
  pending.value = []
  nextTickAutoGrow()
}

function autoGrow() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}
function nextTickAutoGrow() {
  requestAnimationFrame(autoGrow)
}
</script>

<style scoped>
.input-area {
  border-top: 1px solid #ebedf0;
  background: #fff;
  padding: 12px 16px 10px;
}
.pending-atts {
  display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;
}
.pending-item {
  position: relative;
  display: flex; align-items: center; gap: 6px;
  background: #f5f7fa; border-radius: 6px; padding: 4px 8px;
  font-size: 12px;
}
.pending-item img {
  width: 36px; height: 36px; object-fit: cover; border-radius: 4px;
}
.pending-item .name {
  max-width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.pending-item .remove {
  cursor: pointer; color: #c0c4cc;
}
.pending-item .remove:hover { color: #f56c6c; }
.input-row {
  display: flex; align-items: flex-end; gap: 8px;
}
.textarea {
  flex: 1;
  resize: none;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.5;
  min-height: 40px;
  max-height: 200px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s;
}
.textarea:focus { border-color: #3370ff; }
.tip {
  margin-top: 6px;
  font-size: 12px;
  color: #8f959e;
  text-align: center;
}
</style>
