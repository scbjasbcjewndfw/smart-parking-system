<script setup>
/**
 * 车主客服 Agent 页：调 /api/agent/chat/stream，边接收 SSE 边渲染回答。
 *
 * 事件约定（与后端 agentController 一一对应）：
 * - progress 阶段提示，如“正在检索知识库…”
 * - delta    增量文本，追加到当前气泡
 * - reset    校验未通过时用最终文本覆盖气泡（拒答/引用无效）
 * - done     完整结果：sources/steps/ticket_id/transfer 等
 * - error    流式过程中失败，展示错误提示
 *
 * 状态徽章约定（与后端 agentService 返回字段一一对应）：
 * - refused              红色「已转人工」——知识库无法回答，如实拒答
 * - confidence_pending   橙色「业务待确认」——引用了未最终确认条目，需人工复核
 * - ticketId             绿色「工单号」——Agent 建单/转人工后返回
 * - steps                工具调用轨迹（ReAct 每一步的工具、耗时、成败）
 * - sources              回答引用的知识库条目
 */
import { nextTick, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/api/request'

/* ========== 会话状态 ========== */
const messages = ref([])          // {role:'user'|'assistant', text, sources, refused, pending, steps, ticketId}
const question = ref('')
const sending = ref(false)
const listRef = ref(null)

/* 会话 ID 持久化：同一浏览器多轮对话共享记忆，刷新页面不丢上下文 */
const SESSION_KEY = 'agent_session_id'
function sessionId() {
  let id = localStorage.getItem(SESSION_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_KEY, id)
  }
  return id
}

/* 预置问题：覆盖知识库、订单查询、待确认、转人工四种 Agent 行为 */
const suggestions = [
  '停车费怎么算？',
  '能开电子发票吗？',
  '帮我查一下我的停车订单',
  '停车费多扣了，帮我建工单',
]

async function send(text) {
  const q = (text ?? question.value).trim()
  if (!q || sending.value) return

  messages.value.push({ role: 'user', text: q })
  question.value = ''
  sending.value = true

  // 用 reactive 对象承载流式增量，保证直接改字段也能触发渲染
  const bot = reactive({
    role: 'assistant',
    text: '',
    sources: [],
    refused: false,
    pending: false,
    steps: [],
    ticketId: null,
    transfer: false,
    streaming: true,
    stage: '正在连接…',
  })
  messages.value.push(bot)
  scrollToBottom()

  try {
    const token = localStorage.getItem('access_token')
    const base = (request.defaults.baseURL || '/api').replace(/\/$/, '')
    const res = await fetch(`${base}/agent/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question: q, session_id: sessionId() }),
    })
    if (!res.ok) {
      let msg = `请求失败（${res.status}）`
      try {
        const body = await res.json()
        msg = body.msg || msg
      } catch {
        // 非 JSON 错误体，保留默认提示
      }
      throw new Error(msg)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '')

      let sep = buffer.indexOf('\n\n')
      while (sep !== -1) {
        const block = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        sep = buffer.indexOf('\n\n')

        let event = 'message'
        const dataLines = []
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
        }
        if (!dataLines.length) continue

        let data
        try {
          data = JSON.parse(dataLines.join('\n'))
        } catch {
          continue
        }

        if (event === 'progress') {
          bot.stage = data.stage || ''
        } else if (event === 'delta') {
          bot.text += data.text || ''
          bot.stage = ''
          scrollToBottom()
        } else if (event === 'reset') {
          bot.text = data.text || ''
          scrollToBottom()
        } else if (event === 'done') {
          bot.text = data.answer ?? bot.text
          bot.sources = data.sources || []
          bot.refused = Boolean(data.refused)
          bot.pending = Boolean(data.confidence_pending)
          bot.steps = data.steps || []
          bot.ticketId = data.ticket_id
          bot.transfer = Boolean(data.transfer)
          bot.streaming = false
          bot.stage = ''
        } else if (event === 'error') {
          throw new Error(data.msg || '问答失败')
        }
      }
    }
  } catch (err) {
    ElMessage.error('问答服务暂不可用：' + (err.message || err))
    if (!bot.text) bot.text = '抱歉，客服服务暂不可用，请稍后再试。'
  } finally {
    bot.streaming = false
    bot.stage = ''
    sending.value = false
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
</script>

<template>
  <div class="kb-chat">
    <!-- 对话记录 -->
    <div ref="listRef" class="msg-list">
      <div v-if="messages.length === 0" class="empty-hint">
        <p>我是客服 Agent，会按需调用知识库、订单查询、工单与转人工工具。</p>
        <div class="suggest-row">
          <el-button v-for="s in suggestions" :key="s" size="small" plain @click="send(s)">
            {{ s }}
          </el-button>
        </div>
      </div>

      <div
        v-for="(m, i) in messages"
        :key="i"
        class="msg-row"
        :class="m.role === 'user' ? 'msg-user' : 'msg-bot'"
      >
        <div class="bubble" :class="m.role === 'user' ? 'bubble-user' : 'bubble-bot'">
          <div v-if="m.streaming && !m.text" class="stream-hint">
            {{ m.stage || '正在思考…' }}
          </div>
          <div v-else class="bubble-text">
            {{ m.text }}<span v-if="m.streaming" class="stream-cursor">▍</span>
          </div>

          <!-- 状态徽章 + 引用条目（仅助手消息） -->
          <template v-if="m.role === 'assistant'">
            <div v-if="m.refused || m.pending || m.ticketId || m.transfer" class="badges">
              <el-tag v-if="m.refused" type="danger" size="small">已转人工客服</el-tag>
              <el-tag v-if="m.transfer" type="success" size="small">已转人工</el-tag>
              <el-tag v-if="m.pending" type="warning" size="small">业务待确认</el-tag>
              <el-tag v-if="m.ticketId" type="success" size="small" effect="plain">
                工单号 {{ m.ticketId }}
              </el-tag>
            </div>
            <div v-if="m.steps && m.steps.length" class="steps">
              <span v-for="(s, j) in m.steps" :key="j">
                第{{ s.step }}步 {{ s.tool }} {{ s.ok ? '✓' : '✗' }} {{ s.latency_ms }}ms
              </span>
            </div>
            <div v-if="m.sources && m.sources.length" class="sources">
              <el-tag
                v-for="s in m.sources"
                :key="s.kb_id"
                size="small"
                type="info"
                effect="plain"
              >
                <el-tooltip :content="`${s.title}（${s.source || '无来源'}）`" placement="top">
                  <span>{{ s.kb_id }}</span>
                </el-tooltip>
              </el-tag>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-row">
      <el-input
        v-model="question"
        placeholder="输入问题，如：停车费怎么算？"
        :disabled="sending"
        @keyup.enter="send()"
      />
      <el-button type="primary" :loading="sending" @click="send()">发送</el-button>
    </div>
  </div>
</template>

<style scoped>
.kb-chat {
  display: flex;
  flex-direction: column;
  height: 560px;
}

.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px;
}

.empty-hint {
  text-align: center;
  color: #909399;
  margin-top: 120px;
}

.suggest-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 12px;
}

.msg-row {
  display: flex;
  margin-bottom: 12px;
}

.msg-user {
  justify-content: flex-end;
}

.msg-bot {
  justify-content: flex-start;
}

.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.bubble-user {
  background: #409eff;
  color: #fff;
}

.bubble-bot {
  background: #f4f4f5;
  color: #303133;
}

.typing {
  color: #909399;
}

.stream-hint {
  color: #909399;
  font-size: 13px;
}

.stream-cursor {
  margin-left: 1px;
  animation: blink 1s steps(1) infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.badges {
  margin-top: 8px;
  display: flex;
  gap: 6px;
}

.sources {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.steps {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: #909399;
}

.input-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
