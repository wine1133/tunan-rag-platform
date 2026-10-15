<template>
  <div class="qa-workbench" style="min-height: 100vh">
    <!-- 左侧：选应用 + 自己的历史对话 -->
    <div class="qa-side">
      <div class="side-block">
        <div class="side-label">问答应用</div>
        <!-- 只列管理员启用的应用，停用的用户端看不到；选中后 change 事件直接开一个新会话 -->
        <el-select v-model="data.appId" placeholder="请选择问答应用" style="width: 100%" @change="startSession">
          <el-option
              v-for="app in data.appOptions"
              :key="app.id"
              :label="app.name"
              :value="app.id"
          ></el-option>
        </el-select>
        <el-button type="primary" style="width: 100%; margin-top: 10px" @click="startSession">＋ 新建对话</el-button>
      </div>

      <div class="side-block side-history">
        <div class="side-label">我的对话</div>
        <div class="history-list">
          <!-- 点任意一条历史记录载入这次会话，当前打开的那条加 is-current 高亮 -->
          <div
              v-for="session in data.sessions"
              :key="session.id"
              :class="['history-item', session.id === data.sessionId ? 'is-current' : '']"
              @click="openSession(session)"
          >
            <div class="history-title line1">{{ session.title || '新对话' }}</div>
            <div class="history-time">{{ session.create_time }}</div>
            <!-- 删除按钮平时不显示，鼠标移到这一条上才出来；
                 stop 修饰符拦住冒泡，否则点删除会先把这个会话载入进来 -->
            <el-icon class="history-del" @click.stop="removeSession(session)"><Delete /></el-icon>
          </div>
          <div v-if="!data.sessions.length" class="history-empty">还没有对话记录</div>
        </div>
      </div>
    </div>

    <!-- 右侧：对话区 -->
    <div class="qa-main">
      <div ref="listRef" class="chat-list">
        <div v-for="(message, index) in data.messages" :key="index" class="chat-row">
          <div :class="['bubble-line', message.role === 'user' ? 'is-user' : 'is-assistant']">
            <div class="bubble">
              <!-- 提问按原样显示，回答是 Markdown，交给组件渲染 -->
              <span v-if="message.role === 'user'" class="plain-text">{{ message.content }}</span>
              <template v-else>
                <!-- 检索和首个字之间有几秒空档，这里显示当前进行到哪一步，
                     正文一到就换成真正的内容，避免页面看起来像卡死 -->
                <div v-if="message.phase && !message.content" class="qa-phase">
                  <span class="qa-phase-dot"></span>{{ message.phase }}
                </div>
                <MarkdownText v-else :content="message.content" />
              </template>
              <span v-if="message.streaming && message.content" class="caret">▍</span>
            </div>
          </div>

          <!-- 重试轨迹：Agent 每退回去重来一次就记一条，说明这次为什么慢 -->
          <div v-if="message.retries && message.retries.length" class="qa-retry">
            <div v-for="(item, i) in message.retries" :key="i">↻ 第 {{ i + 1 }} 次：{{ item }}</div>
          </div>
          <!-- Agentic 应用才有这行，说明这次自己跑了几步 -->
          <div v-if="message.agent" class="agent-line">
            {{ message.agent.finish_reason }} · 共 {{ message.agent.total_step }} 步 ·
            检索 {{ message.agent.retrieve_count }} 次 · 改写 {{ message.agent.retry_count }} 次
          </div>

          <!-- 引用来源在正文之前就到了，折叠放着，想核对出处再展开 -->
          <div v-if="message.references && message.references.length" class="reference-box">
            <el-collapse>
              <el-collapse-item :title="'引用来源（' + message.references.length + ' 条）'">
                <div v-for="reference in message.references" :key="reference.chunk_id" class="reference-item">
                  <div class="reference-meta">
                    <span>#{{ reference.rank_no }}</span>
                    <span>片段 {{ reference.chunk_id }}</span>
                    <span v-if="reference.score !== null">相关度 {{ reference.score }}</span>
                  </div>
                  <div class="reference-text">{{ reference.content }}</div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- 回答生成完才让打分，流式过程中不显示按钮 -->
          <div v-if="message.role === 'assistant' && message.messageId && !message.streaming" class="feedback-line">
            <el-button
                link
                :type="message.feedback === '点赞' ? 'primary' : 'info'"
                size="small"
                @click="submitFeedback(message, '点赞')"
            >👍 有用</el-button>
            <el-button
                link
                :type="message.feedback === '点踩' ? 'danger' : 'info'"
                size="small"
                @click="submitFeedback(message, '点踩')"
            >👎 没帮助</el-button>
          </div>
        </div>

        <div v-if="!data.messages.length" class="chat-empty">
          <div class="empty-title">{{ data.appId ? '开始提问吧' : '先在左边选一个问答应用' }}</div>
          <div class="empty-tip">回答基于企业知识库检索生成，每条都会附上引用来源</div>
        </div>
      </div>

      <div class="chat-input">
        <el-input
            v-model="data.question"
            type="textarea"
            :rows="3"
            resize="none"
            placeholder="输入问题，回车发送，Shift + 回车换行"
            @keyup.enter.exact="ask"
        ></el-input>
        <div class="input-bar">
          <span class="session-no" v-if="data.sessionNo">当前会话 {{ data.sessionNo.slice(0, 8) }}</span>
          <el-button type="primary" :loading="data.sending" @click="ask">发 送</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'
import { streamPost } from '@/utils/sse.js'
import MarkdownText from '@/components/MarkdownText.vue'
import { Delete } from '@element-plus/icons-vue'

// Agentic 链路每跑完一个节点会发一条 progress 事件，
// 这里把"刚跑完的节点"翻译成"接下来在做什么"，作为等待期间的提示
const AGENT_PHASE = {
  rewrite: '正在检索知识库',
  retrieve: '正在判断召回的资料相不相关',
  grade: '正在生成答案',
  generate: '正在校验答案有没有资料支撑',
  check: '正在整理输出',
  fallback: '正在整理输出'
}

/**
 * 把一条 progress 事件翻译成页面上的两样东西：
 * phase 是当前进行到哪一步，retry 是这一步导致的重试说明（没有重试就是空）。
 *
 * detail 是节点的判定结论：grade 给出 relevant，check 给出 grounded。
 * 判定不通过时状态图会退回去重来，这里把原因说清楚，
 * 用户才知道多等的这几秒 Agent 在干什么，而不是以为卡住了。
 */
const readProgress = (payload) => {
  const detail = payload.detail || {}
  if (payload.node === 'grade' && detail.relevant === false) {
    return { phase: '召回的资料不相关，正在改写问题重新检索', retry: '召回资料不相关，改写问题重新检索' }
  }
  if (payload.node === 'check' && detail.grounded === false) {
    return { phase: '答案缺少资料支撑，正在重新生成', retry: '答案缺少资料支撑，重新生成' }
  }
  // rewrite 节点在重试时 step_name 本身就是"第 N 次改写查询"，直接用它更准确
  if (payload.node === 'rewrite' && payload.name.includes('改写')) {
    return { phase: payload.name + '完成，正在重新检索', retry: '' }
  }
  return { phase: AGENT_PHASE[payload.node] || ('正在' + payload.name), retry: '' }
}

const listRef = ref()

const data = reactive({
  user: JSON.parse(localStorage.getItem('xm-user') || '{}'),
  // 已启用的问答应用，来自 /qaApp/selectEnabled
  appOptions: [],
  appId: '',
  // 自己的历史会话，来自 /qaApp/mySessions
  sessions: [],
  // 当前会话
  sessionId: 0,
  sessionNo: '',
  // 当前会话是在哪个应用下开的。换应用时要另开一个会话，
  // 靠它和 appId 比对，避免把新问题问进上一个应用的会话里
  sessionAppId: 0,
  // 对话消息，每项含 role、content、references、agent
  messages: [],
  question: '',
  sending: false
})

const loadApps = () => {
  request.get('/qaApp/selectEnabled').then(res => {
    if (res.code === '200') {
      data.appOptions = res.data || []
      // 只有一个应用时直接选上，省掉一次点击
      if (data.appOptions.length === 1) {
        data.appId = data.appOptions[0].id
      }
    }
  })
}

const loadSessions = () => {
  // 只取自己的会话，后端从 token 里拿 user_id，前端传不了别人的
  request.get('/qaApp/mySessions', { params: { page_num: 1, page_size: 20 } }).then(res => {
    if (res.code === '200') {
      data.sessions = res.data.list || []
    }
  })
}

const startSession = () => {
  if (!data.appId) {
    ElMessage.warning('请先选择问答应用')
    return
  }
  // 当前这个会话刚建出来、一句话还没问，而且应用也没换，就不再建一条。
  // 不拦的话连点几次"新建对话"会在左边堆出一串空的"新对话"
  if (data.sessionId && !data.messages.length && data.sessionAppId === data.appId) {
    ElMessage.info('当前已经是一个新对话，直接提问就行')
    return
  }
  // 开新会话就是清空对话区，之前的对话已经落库，在左边的列表里能找回来
  data.messages = []
  data.sessionId = 0
  data.sessionNo = ''
  request.post('/qaApp/session', { app_id: data.appId, source: '用户端' }).then(res => {
    if (res.code === '200') {
      data.sessionId = res.data.session_id
      data.sessionNo = res.data.session_no
      data.sessionAppId = data.appId
      // 建完立刻刷新左边的列表，新对话马上出现在最上面并高亮成当前会话，
      // 用户能看见它已经建出来了，不会因为没反馈而反复点
      loadSessions()
    } else {
      // 应用停用、没挂知识库、挂的库都停用了，后端返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const removeSession = (session) => {
  ElMessageBox.confirm(
    `确定删除对话「${session.title || '新对话'}」吗？这次对话的提问、回答和反馈都会一起删掉。`,
    '删除确认',
    { type: 'warning' }
  ).then(() => {
    request.delete('/qaApp/session/' + session.id).then(res => {
      if (res.code !== '200') {
        ElMessage.error(res.msg)
        return
      }
      ElMessage.success('已删除')
      // 删掉的正好是当前打开的这个，对话区要一并清空，
      // 否则页面上还留着一段已经不存在的对话
      if (session.id === data.sessionId) {
        data.messages = []
        data.sessionId = 0
        data.sessionNo = ''
        data.sessionAppId = 0
      }
      loadSessions()
    })
  }).catch(() => {})
}

const openSession = (session) => {
  // 点历史对话，把这个会话的消息完整拉回来接着聊
  data.sessionId = session.id
  data.sessionNo = session.session_no
  data.appId = session.app_id
  data.sessionAppId = session.app_id
  request.get('/qaApp/messages/' + session.id).then(res => {
    if (res.code !== '200') {
      ElMessage.error(res.msg)
      return
    }
    const list = res.data || []
    data.messages = list.map(item => ({
      role: item.role,
      content: item.content,
      references: item.references || [],
      agent: null,
      streaming: false,
      messageId: item.id,
      feedback: ''
    }))
    scrollToBottom()
    loadFeedback(list)
  })
}

const loadFeedback = (list) => {
  // 把自己点过的赞/踩回填到按钮上，不然翻回历史对话会以为没点过
  const ids = list.filter(item => item.role === 'assistant').map(item => item.id)
  if (!ids.length) {
    return
  }
  request.post('/feedback/byMessages', { message_ids: ids }).then(res => {
    if (res.code === '200') {
      const grouped = res.data || {}
      data.messages.forEach(message => {
        const stats = grouped[message.messageId]
        if (stats) {
          message.feedback = stats.mine || ''
        }
      })
    }
  })
}

const scrollToBottom = () => {
  // 每次追加内容后滚到底，让最新的消息始终可见
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}

const ask = async () => {
  const question = data.question.trim()
  if (!question) {
    return
  }
  if (!data.sessionId) {
    // 用户没点“新建对话”就直接问，这里替他开一个，别拿报错挡人
    if (!data.appId) {
      ElMessage.warning('请先选择问答应用')
      return
    }
    await openSessionSilently()
    if (!data.sessionId) {
      return
    }
  }
  data.sending = true
  // 先把提问放进列表，不用等接口返回
  data.messages.push({ role: 'user', content: question })
  // 再放一条空的回答，正文靠 delta 事件一点点填进去
  const reply = reactive({
    role: 'assistant',
    content: '',
    references: [],
    agent: null,
    streaming: true,
    // 正文到达之前显示的阶段文案，收到第一个 delta 就清空
    phase: '正在检索知识库',
    // Agentic 链路每次改写重试都往里追加一条，回答出来之后仍然保留
    retries: [],
    // done 事件里带回来的消息 ID，点赞点踩要用它
    messageId: 0,
    feedback: ''
  })
  data.messages.push(reply)
  data.question = ''
  scrollToBottom()

  try {
    await streamPost('/qaApp/ask', { session_id: data.sessionId, question }, (event, payload) => {
      if (event === 'reference') {
        // 收到引用来源说明检索已经结束，接下来是模型生成
        // 引用来源在正文之前就到了，先渲染出来
        reply.references = payload.references || []
        reply.phase = '已检索到资料，正在生成答案'
      } else if (event === 'progress') {
        // Agentic 专有事件，直线链路不会收到
        const step = readProgress(payload)
        reply.phase = step.phase
        // 重试轨迹留在气泡下方，回答出来之后也不清掉，
        // 它解释了这次为什么绕了几圈、慢在哪里
        if (step.retry) {
          reply.retries.push(step.retry)
        }
      } else if (event === 'agent') {
        reply.agent = payload
      } else if (event === 'delta') {
        // 第一个字到了就不用再显示阶段提示
        // 正文增量，一段一段拼进去
        reply.content += payload.text
        reply.phase = ''
        scrollToBottom()
      } else if (event === 'done') {
        reply.messageId = payload.message_id
      } else if (event === 'error') {
        reply.content = payload.message
        reply.phase = ''
        ElMessage.error(payload.message)
      }
    })
  } finally {
    reply.streaming = false
    // 整条流结束还没拿到正文时，phase 也要清掉，不然提示会一直转
    reply.phase = ''
    data.sending = false
    scrollToBottom()
    // 首轮提问会把会话标题写成这句话，刷新左边列表才能看到
    loadSessions()
  }
}

const openSessionSilently = () => {
  return request.post('/qaApp/session', { app_id: data.appId, source: '用户端' }).then(res => {
    if (res.code === '200') {
      data.sessionId = res.data.session_id
      data.sessionNo = res.data.session_no
      data.sessionAppId = data.appId
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const submitFeedback = (message, type) => {
  // 同一条回答再点一次会覆盖上一次，后端只保留最后的结果
  request.post('/feedback/submit', {
    message_id: message.messageId,
    feedback_type: type
  }).then(res => {
    if (res.code === '200') {
      message.feedback = type
      ElMessage.success(type === '点赞' ? '感谢反馈' : '已记录，这个问题会进入优化清单')
    } else {
      ElMessage.error(res.msg)
    }
  })
}

if (!data.user.id) {
  ElMessage.warning('请先登录后再使用问答')
} else {
  loadApps()
  loadSessions()
}
</script>

<style scoped>
.qa-workbench {
  display: flex;
  gap: 16px;
  width: 92%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 16px 0 24px;
  /* 顶部导航栏和页脚一共约 150px，减掉才不会把页面撑出滚动条 */
  height: calc(100vh - 150px);
  min-height: 520px;
}

/* ---------- 左侧 ---------- */
.qa-side {
  width: 260px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.side-block {
  background-color: #fff;
  border: 1px solid #e6e9f0;
  border-radius: 8px;
  padding: 14px;
}

.side-history {
  flex: 1;
  /* 列表自己滚动，不把整页撑长 */
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.side-label {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 10px;
}

.history-list {
  flex: 1;
  overflow: auto;
  margin: 0 -6px;
}

.history-item {
  position: relative;
  padding: 9px 28px 9px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color .18s;
}

/* 删除图标压在右侧，平时透明，鼠标移到这一条上才显形 */
.history-del {
  position: absolute;
  right: 8px;
  top: 10px;
  font-size: 13px;
  color: #a3aab8;
  opacity: 0;
  transition: opacity .18s, color .18s;
}

.history-item:hover .history-del {
  opacity: 1;
}

.history-del:hover {
  color: #dc2626;
}

.history-item:hover {
  background-color: #f4f6fa;
}

.history-item.is-current {
  background-color: #eef4ff;
}

.history-title {
  font-size: 13px;
  color: #374151;
}

.history-time {
  margin-top: 3px;
  font-size: 11px;
  color: #a3aab8;
}

.history-empty {
  padding: 20px 10px;
  font-size: 13px;
  color: #a3aab8;
  text-align: center;
}

/* ---------- 右侧 ---------- */
.qa-main {
  flex: 1;
  /* 配合 flex:1，防止长文本把右侧撑宽 */
  width: 0;
  display: flex;
  flex-direction: column;
  background-color: #fff;
  border: 1px solid #e6e9f0;
  border-radius: 8px;
  overflow: hidden;
}

.chat-list {
  flex: 1;
  overflow: auto;
  padding: 20px 24px;
}

.chat-row {
  margin-bottom: 18px;
}

.bubble-line {
  display: flex;
}

.bubble-line.is-user {
  justify-content: flex-end;
}

.bubble {
  max-width: 78%;
  padding: 11px 15px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}

/* 用户提问不走 Markdown 渲染，换行按原样显示 */
.plain-text {
  white-space: pre-wrap;
}

/* 正文到达之前的等待提示：一个呼吸的小圆点 + 会跳动的省略号 */
.qa-phase {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #9096a3;
}

.qa-phase::after {
  content: '';
  animation: qa-dots 1.2s steps(1, end) infinite;
}

.qa-retry {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.9;
  color: #d97706;
}

.qa-phase-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #2563eb;
  animation: qa-pulse 1s ease-in-out infinite;
}

@keyframes qa-pulse {
  0%, 100% { opacity: .25; transform: scale(.8); }
  50% { opacity: 1; transform: scale(1.15); }
}

@keyframes qa-dots {
  0% { content: ''; }
  25% { content: '.'; }
  50% { content: '..'; }
  75% { content: '...'; }
}

.is-user .bubble {
  color: #fff;
  background-color: #2563eb;
  border-bottom-right-radius: 3px;
}

.is-assistant .bubble {
  color: #1f2937;
  background-color: #f4f6fa;
  border-bottom-left-radius: 3px;
}

.caret {
  color: #9096a3;
}

.agent-line {
  margin-top: 6px;
  font-size: 12px;
  color: #9096a3;
}

.reference-box {
  margin-top: 6px;
  max-width: 78%;
}

.reference-item {
  margin-bottom: 10px;
}

.reference-meta {
  display: flex;
  gap: 10px;
  font-size: 12px;
  color: #9096a3;
}

.reference-text {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.7;
  color: #6b7280;
}

.feedback-line {
  margin-top: 4px;
}

.chat-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: #9096a3;
}

.empty-title {
  font-size: 16px;
  color: #6b7280;
}

.empty-tip {
  margin-top: 8px;
  font-size: 13px;
}

.chat-input {
  border-top: 1px solid #eef0f5;
  padding: 12px 16px 14px;
}

.input-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 10px;
}

.session-no {
  font-size: 12px;
  color: #a3aab8;
}

.chat-input :deep(.el-textarea__inner) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #e3e6ee inset;
}

.chat-input :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 1px #2563eb inset;
}

/* 窄屏把左侧列表收起来，优先保证对话区可用 */
@media (max-width: 1000px) {
  .qa-side {
    display: none;
  }
  .qa-workbench {
    width: 96%;
  }
}
</style>
