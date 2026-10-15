<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 换应用会开一个新会话，之前的对话留在会话记录里 -->
      <el-select v-model="data.appId" style="width: 260px; margin-right: 10px" placeholder="请选择问答应用" @change="startSession">
        <el-option
            v-for="app in data.appOptions"
            :key="app.id"
            :label="app.name + (app.agent_enabled === '是' ? '（Agentic）' : '')"
            :value="app.id"
        ></el-option>
      </el-select>
      <!-- 开新会话等于清空当前对话，重新开始一轮 -->
      <el-button type="warning" plain @click="startSession">新建会话</el-button>
      <span v-if="data.sessionNo" style="margin-left: 12px; color: #999; font-size: 12px">
        当前会话：{{ data.sessionNo.slice(0, 8) }}
      </span>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- 对话区，固定高度加滚动，新消息追加在下方 -->
      <div ref="listRef" style="height: 460px; overflow: auto; padding: 10px">
        <div v-for="(message, index) in data.messages" :key="index" style="margin-bottom: 16px">
          <!-- 用户消息靠右，助手消息靠左 -->
          <div :style="{ textAlign: message.role === 'user' ? 'right' : 'left' }">
            <div
                :style="{
                  display: 'inline-block',
                  maxWidth: '80%',
                  textAlign: 'left',
                  padding: '10px 14px',
                  borderRadius: '6px',
                  background: message.role === 'user' ? '#ecf5ff' : '#f7f7f7'
                }"
            >
              <!-- 提问是用户敲的纯文本，按原样显示；回答是模型输出的 Markdown，交给组件渲染 -->
              <span v-if="message.role === 'user'" style="white-space: pre-wrap">{{ message.content }}</span>
              <template v-else>
                <!-- 检索和首个字之间有几秒空档，这里显示当前进行到哪一步，
                     正文一到就换成真正的内容，避免页面看起来像卡死 -->
                <div v-if="message.phase && !message.content" class="qa-phase">
                  <span class="qa-phase-dot"></span>{{ message.phase }}
                </div>
                <MarkdownText v-else :content="message.content" />
              </template>
              <span v-if="message.streaming && message.content" style="color: #999">▍</span>
            </div>
          </div>
          <!-- 重试轨迹：Agent 每退回去重来一次就记一条，说明这次为什么慢 -->
          <div v-if="message.retries && message.retries.length" class="qa-retry">
            <div v-for="(item, i) in message.retries" :key="i">↻ 第 {{ i + 1 }} 次：{{ item }}</div>
          </div>
          <!-- Agentic 模式下把这次跑了几步、检索了几次显示出来 -->
          <div v-if="message.agent" style="margin-top: 6px; font-size: 12px; color: #999">
            {{ message.agent.finish_reason }} · 共 {{ message.agent.total_step }} 步 ·
            检索 {{ message.agent.retrieve_count }} 次 · 改写 {{ message.agent.retry_count }} 次
            <el-button link type="primary" size="small" @click="viewRun(message.agent.run_id)">查看时间线</el-button>
          </div>
          <!-- 回答生成完之后才能打分，流式过程中不显示按钮 -->
          <div v-if="message.role === 'assistant' && message.messageId && !message.streaming" style="margin-top: 6px">
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
          <!-- 引用来源在正文之前就收到了，这里折叠展示 -->
          <div v-if="message.references && message.references.length" style="margin-top: 6px">
            <el-collapse>
              <el-collapse-item :title="'引用来源（' + message.references.length + ' 条）'">
                <div v-for="reference in message.references" :key="reference.chunk_id" style="margin-bottom: 8px; font-size: 12px; color: #666">
                  <span style="margin-right: 8px">#{{ reference.rank_no }}</span>
                  <span style="margin-right: 8px">片段 {{ reference.chunk_id }}</span>
                  <span style="margin-right: 8px">分数 {{ reference.score }}</span>
                  <div>{{ reference.content }}</div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
        <div v-if="!data.messages.length" style="color: #999; text-align: center; padding-top: 180px">
          选择一个应用，开始提问
        </div>
      </div>
    </div>

    <div class="card">
      <el-input
          v-model="data.question"
          type="textarea"
          :rows="2"
          placeholder="输入问题，回车发送"
          @keyup.enter.exact="ask"
      ></el-input>
      <div style="margin-top: 10px; text-align: right">
        <el-button type="primary" :loading="data.sending" @click="ask">发送</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'
import router from '@/router/index.js'
import { streamPost } from '@/utils/sse.js'
import MarkdownText from '@/components/MarkdownText.vue'

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
  // 应用下拉选项，来自 /qaApp/selectEnabled
  appOptions: [],
  appId: '',
  // 当前会话
  sessionId: 0,
  sessionNo: '',
  // 对话消息列表，每项含 role、content、references、agent
  messages: [],
  question: '',
  sending: false
})

const loadApps = () => {
  request.get('/qaApp/selectEnabled').then(res => {
    if (res.code === '200') {
      data.appOptions = res.data || []
      // 从应用管理页跳过来时地址栏带着 appId，自动选中并开会话
      const appId = router.currentRoute.value.query.appId
      if (appId) {
        data.appId = Number(appId)
        startSession()
      }
    }
  })
}

const startSession = () => {
  if (!data.appId) {
    return
  }
  // 开新会话时清空当前对话区，之前的对话已经落库，在会话记录里能查到
  data.messages = []
  request.post('/qaApp/session', { app_id: data.appId, source: '管理端' }).then(res => {
    if (res.code === '200') {
      data.sessionId = res.data.session_id
      data.sessionNo = res.data.session_no
    } else {
      // 应用停用、没挂知识库、挂的库都停用了，后端返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const scrollToBottom = () => {
  // 每次追加内容后滚到底部，让最新的消息始终可见
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}

const ask = async () => {
  if (!data.sessionId) {
    ElMessage.warning('请先选择问答应用')
    return
  }
  const question = data.question.trim()
  if (!question) {
    return
  }
  data.sending = true
  // 先把用户这条消息放进列表，不用等接口返回
  data.messages.push({ role: 'user', content: question })
  // 再放一条空的助手消息，正文靠 delta 事件一点点填进去
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
        // 引用来源在正文之前就到了，先渲染出来；
        // 收到它说明检索这一步已经结束，接下来是模型生成
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
        // Agentic 模式才有这个事件，带着这次跑了几步
        reply.agent = payload
      } else if (event === 'delta') {
        // 正文增量，一段一段拼进去；第一个字到了就不用再显示阶段提示
        // 正文增量，一段一段拼进去
        reply.content += payload.text
        reply.phase = ''
        scrollToBottom()
      } else if (event === 'done') {
        // 拿到这条回答的消息 ID，点赞点踩按钮才能用
        reply.messageId = payload.message_id
      } else if (event === 'error') {
        reply.content = payload.message
        reply.phase = ''
        ElMessage.error(payload.message)
      }
    })
  } finally {
    reply.streaming = false
    // 整条流结束还没拿到正文时，phase 也要清掉，不然会一直转
    reply.phase = ''
    data.sending = false
    scrollToBottom()
  }
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

const viewRun = (runId) => {
  // 跳到第 23 章的运行记录页，直接打开这次的执行时间线
  router.push('/manager/agentRun?runId=' + runId)
}

loadApps()
</script>

<style scoped>
/* 正文到达之前的等待提示：一个呼吸的小圆点 + 会跳动的省略号，
   让用户知道请求还在跑，而不是页面卡死了 */
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
</style>
