<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 三个数字看整体满意度，点踩待沉淀数是第 27 章要处理的存量 -->
      <span style="margin-right: 20px">点赞 {{ data.summary.liked }}</span>
      <span style="margin-right: 20px">点踩 {{ data.summary.disliked }}</span>
      <span style="margin-right: 20px">满意度 {{ data.summary.satisfaction ?? '—' }}%</span>
      <el-tag v-if="data.summary.pending_convert" type="warning" size="small">
        {{ data.summary.pending_convert }} 条点踩待沉淀成评测用例
      </el-tag>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-radio-group v-model="data.tab" @change="switchTab">
        <el-radio-button value="session">对话日志</el-radio-button>
        <el-radio-button value="feedback">用户反馈</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 对话日志：一个会话一行，点踩多的会话优先看 -->
    <div class="card" style="margin-bottom: 5px" v-if="data.tab === 'session'">
      <div style="margin-bottom: 10px">
        <el-input v-model="data.keyword" style="width: 240px; margin-right: 10px" placeholder="按会话标题搜索"></el-input>
        <el-button type="info" plain @click="load">查询</el-button>
      </div>
      <el-table stripe :data="data.tableData">
        <el-table-column prop="id" label="会话ID" width="90" />
        <el-table-column prop="app_name" label="所属应用" width="180" />
        <el-table-column prop="title" label="会话标题" show-overflow-tooltip />
        <el-table-column prop="message_count" label="消息数" width="90" />
        <el-table-column prop="source" label="来源" width="100" />
        <!-- 点赞数只做展示，不参与排查，用绿色 -->
        <el-table-column prop="like_count" label="点赞" width="80">
          <template #default="scope">
            <el-tag v-if="scope.row.like_count" type="success" size="small">{{ scope.row.like_count }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <!-- 点踩次数不为 0 的标红，一眼扫出哪些对话有问题 -->
        <el-table-column prop="dislike_count" label="点踩" width="80">
          <template #default="scope">
            <el-tag v-if="scope.row.dislike_count" type="danger" size="small">{{ scope.row.dislike_count }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="时间" width="180" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="scope">
            <el-button type="primary" size="small" @click="viewMessages(scope.row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 用户反馈：一条反馈一行，带着当时的问题和回答 -->
    <div class="card" style="margin-bottom: 5px" v-if="data.tab === 'feedback'">
      <div style="margin-bottom: 10px">
        <el-select v-model="data.feedbackType" clearable style="width: 140px; margin-right: 10px" placeholder="反馈类型">
          <el-option label="点赞" value="点赞"></el-option>
          <el-option label="点踩" value="点踩"></el-option>
        </el-select>
        <el-select v-model="data.converted" clearable style="width: 180px; margin-right: 10px" placeholder="是否已沉淀">
          <el-option label="已沉淀评测用例" value="是"></el-option>
          <el-option label="待沉淀" value="否"></el-option>
        </el-select>
        <el-button type="info" plain @click="load">查询</el-button>
      </div>
      <el-table stripe :data="data.tableData">
        <el-table-column prop="feedback_type" label="类型" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.feedback_type === '点赞' ? 'success' : 'danger'" size="small">{{ scope.row.feedback_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" show-overflow-tooltip />
        <el-table-column prop="answer" label="回答" show-overflow-tooltip />
        <el-table-column prop="reason" label="反馈原因" width="180" show-overflow-tooltip />
        <!-- 第 27 章会把待沉淀的点踩转成评测用例 -->
        <el-table-column prop="converted" label="已沉淀" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.converted === '是' ? 'success' : 'info'" size="small">{{ scope.row.converted }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="时间" width="180" />
      </el-table>
    </div>

    <div class="card" v-if="data.total">
      <el-pagination
          v-model:current-page="data.pageNum"
          background
          layout="prev, pager, next"
          :page-size="data.pageSize"
          :total="data.total"
          @current-change="load"
      />
    </div>

    <!-- 会话详情弹窗：完整的一问一答，含引用来源 -->
    <el-dialog title="对话详情" v-model="data.detailVisible" width="65%" destroy-on-close>
      <div style="max-height: 500px; overflow: auto">
        <div v-for="message in data.messages" :key="message.id" style="margin-bottom: 14px">
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
              <!-- 提问按原样显示，回答按 Markdown 渲染，和问答页保持一致 -->
              <span v-if="message.role === 'user'" style="white-space: pre-wrap">{{ message.content }}</span>
              <MarkdownText v-else :content="message.content" />
            </div>
          </div>
          <!-- 排查召回问题时看这一行：当时实际拿去检索的是什么 -->
          <div v-if="message.rewritten_query" style="font-size: 12px; color: #999; margin-top: 4px">
            实际检索问题：{{ message.rewritten_query }}
          </div>
          <div v-if="message.references && message.references.length" style="margin-top: 6px">
            <el-collapse>
              <el-collapse-item :title="'引用来源（' + message.references.length + ' 条）'">
                <div v-for="reference in message.references" :key="reference.chunk_id" style="margin-bottom: 8px; font-size: 12px; color: #666">
                  <span style="margin-right: 8px">#{{ reference.rank_no }}</span>
                  <span style="margin-right: 8px">片段 {{ reference.chunk_id }}</span>
                  <div>{{ reference.content }}</div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="data.detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'
import MarkdownText from '@/components/MarkdownText.vue'

const data = reactive({
  // 两个页签共用一张表格，靠 tab 决定查哪个接口
  tab: 'session',
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  keyword: '',
  feedbackType: '',
  converted: '',
  // 顶部的反馈总览
  summary: {},
  // 会话详情弹窗
  detailVisible: false,
  messages: []
})

const loadSummary = () => {
  request.get('/feedback/summary').then(res => {
    if (res.code === '200') {
      data.summary = res.data || {}
    }
  })
}

const load = () => {
  // 会话页签走会话列表接口，keyword 是顶部搜索框里输入的会话标题关键字
  if (data.tab === 'session') {
    request.get('/feedback/sessions', {
      params: { page_num: data.pageNum, page_size: data.pageSize, keyword: data.keyword }
    }).then(res => {
      if (res.code === '200') {
        // 会话列表和分页总数都写进共用的 tableData 和 total，分页条据此渲染
        data.tableData = res.data?.list || []
        data.total = res.data?.total || 0
      } else {
        ElMessage.error(res.msg)
      }
    })
    // 会话页签的请求已经发出去了，不能再往下走反馈页签那一段
    return
  }
  // 反馈页签走反馈明细接口，feedbackType 是点赞点踩下拉框，converted 是是否已沉淀下拉框
  request.get('/feedback/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      feedback_type: data.feedbackType,
      converted: data.converted
    }
  }).then(res => {
    if (res.code === '200') {
      // 两个页签复用同一份 tableData，所以切页签时必须先清空
      data.tableData = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const switchTab = () => {
  // 换页签时清空条件和页码，两个页签的筛选条件不通用
  data.pageNum = 1
  data.tableData = []
  data.total = 0
  load()
}

const viewMessages = (row) => {
  // 取这个会话的完整消息，含每条回答的引用来源
  request.get('/qaApp/messages/' + row.id).then(res => {
    if (res.code === '200') {
      data.messages = res.data || []
      data.detailVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

loadSummary()
load()
</script>
