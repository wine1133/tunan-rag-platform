<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-form :inline="true" style="padding: 10px 20px 0">
        <el-form-item label="评测集">
          <el-select v-model="data.datasetId" style="width: 260px" placeholder="请选择评测集">
            <el-option
                v-for="item in data.datasets"
                :key="item.id"
                :label="item.name + '（' + item.case_count + ' 条用例）'"
                :value="item.id"
            ></el-option>
          </el-select>
        </el-form-item>
        <!-- 换一套策略再跑一次，就能对比出效果差异 -->
        <el-form-item label="检索策略">
          <el-select v-model="data.strategyId" clearable style="width: 260px" placeholder="不选则使用默认策略">
            <el-option v-for="item in data.strategies" :key="item.id" :label="item.name" :value="item.id"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="start">开始评测</el-button>
        </el-form-item>
      </el-form>
      <div style="padding: 0 20px 10px; color: #999; font-size: 12px">
        一条用例要调六次模型，20 条用例一轮大约几十万输入 token。建议先用 5 条验证方向。
      </div>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <el-table stripe :data="data.tasks">
        <el-table-column prop="id" label="任务ID" width="80" />
        <!-- 几份报告摆一起时，靠这两列分清是哪套题、哪套策略 -->
        <el-table-column prop="dataset_name" label="评测集" min-width="140" show-overflow-tooltip />
        <el-table-column prop="strategy_name" label="检索策略" min-width="150" show-overflow-tooltip />
        <el-table-column prop="task_status" label="状态" width="100">
          <template #default="scope">
            <el-tag :type="statusColor(scope.row.task_status)" size="small">{{ scope.row.task_status }}</el-tag>
          </template>
        </el-table-column>
        <!-- 跑到一半时刷新能看到成功数在涨 -->
        <el-table-column label="进度" width="130">
          <template #default="scope">
            {{ scope.row.success_count }} / {{ scope.row.total_count }}
            <span v-if="scope.row.fail_count" style="color: #f56c6c">（失败 {{ scope.row.fail_count }}）</span>
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="失败原因" show-overflow-tooltip />
        <el-table-column prop="cost_millis" label="耗时（ms）" width="120" />
        <el-table-column prop="create_time" label="时间" width="180" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="scope">
            <el-button type="primary" size="small" @click="viewResults(scope.row.id)">看报告</el-button>
            <!-- 跑废的、参数配错的任务能删掉，免得列表越堆越长分不清哪份是有效的 -->
            <el-button type="danger" size="small" @click="delTask(scope.row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="card" v-if="data.total">
      <el-pagination
          v-model:current-page="data.pageNum"
          background
          layout="prev, pager, next"
          :page-size="data.pageSize"
          :total="data.total"
          @current-change="loadTasks"
      />
    </div>

    <!-- 评测报告弹窗：四个指标的均分 + 每条用例的明细 -->
    <el-dialog title="评测报告" v-model="data.reportVisible" width="80%" destroy-on-close>
      <div v-if="data.detail.report" style="padding-bottom: 12px">
        <div style="margin-bottom: 8px">
          <!-- 评测集名放第一位：换套题分数就没有可比性，先看清评的是哪套题 -->
          <span style="margin-right: 20px">评测集：<b>{{ data.detail.report.dataset_name || '—' }}</b></span>
          <span style="margin-right: 20px">策略：{{ data.detail.report.strategy_name }}</span>
          <span style="margin-right: 20px">用例 {{ data.detail.report.case_count }} 条</span>
          <span>综合得分 {{ data.detail.report.overall_score }}</span>
        </div>
        <!-- 四个指标各一个进度条，低于阈值的自动变红 -->
        <!-- 指标说明、达标线、是否达标都由后端算好放在 metrics 里，前端只负责显示。
             判断“多少算低”的规则和这几句说明文案，都和结论共用一份，不在这里再写一套 -->
        <el-row :gutter="12">
          <el-col :span="6" v-for="metric in (data.detail.report.metrics || [])" :key="metric.field">
            <div style="padding: 10px; background: #f7f7f7; border-radius: 4px; height: 100%">
              <!-- 中英文都列出来：看文档和看论文时对得上号 -->
              <div style="font-size: 13px; color: #333; font-weight: bold">
                {{ metric.label }}
                <el-tag size="small" type="info" style="margin-left: 4px">{{ metric.stage }}</el-tag>
              </div>
              <div style="font-size: 11px; color: #aaa; margin-bottom: 2px">{{ metric.en }}</div>
              <!-- 达标绿、偏低红，没跑出分数时是灰的 —— -->
              <div
                  style="font-size: 24px; font-weight: bold; line-height: 1.4"
                  :style="{ color: metric.ok === null ? '#999' : (metric.ok ? '#67c23a' : '#f56c6c') }"
              >
                {{ metric.value ?? '—' }}
              </div>
              <!-- 这个指标到底在测什么，直接写在卡片上，不用去翻文档 -->
              <div style="font-size: 12px; color: #666; line-height: 1.6; margin-bottom: 4px">
                {{ metric.plain }}
              </div>
              <!-- 达标时只说达标线是多少；偏低时才提示该去调哪一环 -->
              <div style="font-size: 12px; line-height: 1.6" :style="{ color: metric.ok === false ? '#f56c6c' : '#67c23a' }">
                <template v-if="metric.ok === null">
                  <span style="color: #999">未参与统计</span>
                </template>
                <template v-else-if="metric.ok">达标（≥ {{ metric.threshold }}）</template>
                <template v-else>低于 {{ metric.threshold }}：{{ metric.advice }}</template>
              </div>
            </div>
          </el-col>
        </el-row>
        <!-- 结论按第 26 章那张对照表自动生成，直接告诉你该调哪一环 -->
        <el-alert
            :title="data.detail.report.conclusion"
            :type="data.detail.report.conclusion === '四项指标都在合理区间。' ? 'success' : 'warning'"
            :closable="false"
            style="margin-top: 12px"
        />
      </div>
      <el-table stripe :data="data.detail.results" size="small" style="margin-top: 10px" max-height="400">
        <el-table-column prop="question" label="问题" min-width="150" show-overflow-tooltip />
        <!-- 标准答案和生成答案并排，一眼看出是真答错了还是只是话术不同 -->
        <el-table-column prop="ground_truth" label="标准答案" min-width="150" show-overflow-tooltip />
        <el-table-column prop="answer" label="生成的答案" min-width="180" show-overflow-tooltip />
        <el-table-column prop="context_recall" label="召回" width="80" />
        <el-table-column prop="context_precision" label="精度" width="80" />
        <el-table-column prop="faithfulness" label="忠实度" width="90" />
        <el-table-column prop="answer_relevancy" label="相关性" width="90" />
        <el-table-column prop="avg_score" label="均分" width="80" />
        <el-table-column prop="error_message" label="失败原因" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="data.reportVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

// 四个指标的展示配置，hint 是第 26 章那张对照表的浓缩
const data = reactive({
  datasets: [],
  strategies: [],
  datasetId: '',
  strategyId: '',
  tasks: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  reportVisible: false,
  detail: {}
})

const loadOptions = () => {
  request.get('/evalDataset/selectAll').then(res => {
    if (res.code === '200') {
      data.datasets = res.data || []
    }
  })
  request.get('/retrieval/strategies').then(res => {
    if (res.code === '200') {
      data.strategies = res.data || []
    }
  })
}

const loadTasks = () => {
  request.get('/evalTask/selectPage', {
    params: { page_num: data.pageNum, page_size: data.pageSize }
  }).then(res => {
    if (res.code === '200') {
      data.tasks = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const start = () => {
  if (!data.datasetId) {
    ElMessage.warning('请选择评测集')
    return
  }
  request.post('/evalTask/start', {
    dataset_id: data.datasetId,
    strategy_id: data.strategyId || null
  }).then(res => {
    if (res.code === '200') {
      // 接口只建任务就返回，真正的评测在后台跑
      ElMessage.success(res.data)
      loadTasks()
    } else {
      // 没有启用的用例、超过条数上限、评测集没关联知识库，后端都返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const delTask = (id) => {
  ElMessageBox.confirm('删除后这次评测的报告和每条用例的结果都会一起删掉，确认删除？', '确认删除', {
    type: 'warning'
  }).then(() => {
    request.delete('/evalTask/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        // 删完重新拉列表，当前页可能已经空了
        loadTasks()
      } else {
        // 还在跑的任务不允许删，后端返回人话提示
        ElMessage.error(res.msg)
      }
    })
  }).catch(() => {})
}

const viewResults = (taskId) => {
  request.get('/evalTask/results/' + taskId).then(res => {
    if (res.code === '200') {
      data.detail = res.data
      data.reportVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const statusColor = (status) => {
  if (status === '已完成') {
    return 'success'
  }
  if (status === '失败') {
    return 'danger'
  }
  return 'primary'
}

loadOptions()
loadTasks()
</script>
