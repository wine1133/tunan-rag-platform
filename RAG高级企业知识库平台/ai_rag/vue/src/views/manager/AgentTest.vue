<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-form label-width="90px" style="padding: 10px 20px 0">
        <!-- Agent 一次只在一个知识库里跑，检索工具的入参就是一个 kb_id -->
        <el-form-item label="知识库">
          <el-select v-model="data.kbId" style="width: 100%" placeholder="请选择知识库">
            <el-option
                v-for="kb in data.kbOptions"
                :key="kb.id"
                :label="kb.name + '（片段 ' + kb.chunk_count + ' 条）'"
                :value="kb.id"
            ></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="问题">
          <el-input v-model="data.query" type="textarea" :rows="2" placeholder="输入一个问题，看 Agent 怎么一步步找答案"></el-input>
        </el-form-item>
        <el-form-item>
          <!-- Agent 要跑好几轮模型调用，慢的时候十几秒，按钮转圈期间不重复点 -->
          <el-button type="primary" :loading="data.running" @click="run">开始执行</el-button>
          <span style="margin-left: 16px; color: #999; font-size: 12px">
            改写、检索、判断相关、生成、校验，跑几轮由模型的判断决定
          </span>
        </el-form-item>
      </el-form>
    </div>

    <!-- 有结果才显示，进页面时是空的 -->
    <div class="card" style="margin-bottom: 5px" v-if="data.outcome.run_no">
      <div style="padding-bottom: 8px">
        <!-- 正常回答绿色、走了兜底橙色，一眼看出这次有没有找到资料 -->
        <el-tag :type="data.outcome.finish_reason === '正常回答' ? 'success' : 'warning'" style="margin-right: 12px">
          {{ data.outcome.finish_reason }}
        </el-tag>
        <span style="margin-right: 16px">共 {{ data.outcome.total_step }} 步</span>
        <span style="margin-right: 16px">检索 {{ data.outcome.retrieve_count }} 次</span>
        <span style="margin-right: 16px">改写重试 {{ data.outcome.retry_count }} 次</span>
        <span style="margin-right: 16px">耗时 {{ data.outcome.cost_millis }} ms</span>
        <!-- 拿运行ID去时间线页面看每一步的细节 -->
        <el-button type="primary" size="small" @click="viewTimeline">查看执行时间线</el-button>
      </div>
      <!-- Agent 最终答案同样是 Markdown 文本 -->
      <div style="background: #f7f7f7; padding: 12px">
        <MarkdownText :content="data.outcome.answer" />
      </div>
    </div>

    <div class="card" v-if="data.outcome.references && data.outcome.references.length">
      <div style="font-weight: bold; padding-bottom: 8px">引用来源（{{ data.outcome.references.length }} 条）</div>
      <!-- 这些内容全部按 chunk_id 回查数据库得到，不是模型说的 -->
      <el-table stripe :data="data.outcome.references" size="small">
        <el-table-column prop="rank_no" label="序号" width="70" />
        <el-table-column prop="chunk_id" label="片段ID" width="90" />
        <el-table-column prop="page_no" label="页码" width="80">
          <template #default="scope">{{ scope.row.page_no || '-' }}</template>
        </el-table-column>
        <el-table-column prop="score" label="分数" width="100" />
        <el-table-column prop="content" label="片段内容" show-overflow-tooltip />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'
import router from '@/router/index.js'
import MarkdownText from '@/components/MarkdownText.vue'

const data = reactive({
  // 知识库下拉选项，来自 /retrieval/knowledgeBases
  kbOptions: [],
  // 选中的知识库 id
  kbId: '',
  // 问题
  query: '',
  // 执行按钮的转圈状态
  running: false,
  // 执行结果，含 answer、references、finish_reason、各项计数
  outcome: {}
})

const loadOptions = () => {
  request.get('/retrieval/knowledgeBases').then(res => {
    if (res.code === '200') {
      data.kbOptions = res.data || []
    }
  })
}

const run = () => {
  if (!data.kbId) {
    ElMessage.warning('请选择知识库')
    return
  }
  if (!data.query.trim()) {
    ElMessage.warning('请输入问题')
    return
  }
  data.running = true
  request.post('/agent/run', {
    kb_ids: [data.kbId],
    query: data.query
  }).then(res => {
    if (res.code === '200') {
      // res.data 里有答案、引用来源、跑了几步、检索了几次
      data.outcome = res.data
    } else {
      // 没检索过、模型没配好、工具被停用，后端都返回人话提示
      ElMessage.error(res.msg)
    }
  }).finally(() => {
    data.running = false
  })
}

const viewTimeline = () => {
  // 带着运行ID跳到时间线页面，看每一步的入参和返回
  router.push('/manager/agentRun?runId=' + data.outcome.run_id)
}

// 页面加载时取知识库下拉数据
loadOptions()
</script>
