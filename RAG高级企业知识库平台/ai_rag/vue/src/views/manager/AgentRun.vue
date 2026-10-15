<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 只看失败的运行，排查问题时最常用 -->
      <el-select v-model="data.runStatus" clearable style="width: 160px; margin-right: 10px" placeholder="运行状态">
        <el-option label="已完成" value="已完成"></el-option>
        <el-option label="运行失败" value="运行失败"></el-option>
        <el-option label="运行中" value="运行中"></el-option>
      </el-select>
      <el-button type="info" plain @click="load">查询</el-button>
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /agent/runs 返回的 list -->
      <el-table stripe :data="data.tableData">
        <el-table-column prop="id" label="运行ID" width="90" />
        <el-table-column prop="run_type" label="类型" width="120" />
        <el-table-column prop="run_status" label="状态" width="100">
          <template #default="scope">
            <el-tag :type="statusColor(scope.row.run_status)" size="small">{{ scope.row.run_status }}</el-tag>
          </template>
        </el-table-column>
        <!-- 总步数、检索次数、改写次数三个数字画出这次运行的形状 -->
        <el-table-column prop="total_step" label="步数" width="80" />
        <el-table-column prop="retrieve_count" label="检索" width="80" />
        <el-table-column prop="rewrite_count" label="改写" width="80" />
        <el-table-column prop="output_summary" label="最终结论" show-overflow-tooltip />
        <el-table-column prop="error_message" label="失败原因" show-overflow-tooltip />
        <el-table-column prop="cost_millis" label="耗时（ms）" width="110" />
        <el-table-column prop="create_time" label="时间" width="180" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="scope">
            <el-button type="primary" size="small" @click="viewTimeline(scope.row.id)">时间线</el-button>
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
          @current-change="load"
      />
    </div>

    <!-- 执行时间线弹窗：这次运行每一步做了什么、判断结果是什么 -->
    <el-dialog title="执行时间线" v-model="data.timelineVisible" width="70%" destroy-on-close>
      <div v-if="data.timeline.run" style="padding-bottom: 12px">
        <el-tag :type="statusColor(data.timeline.run.run_status)" style="margin-right: 12px">{{ data.timeline.run.run_status }}</el-tag>
        <span style="margin-right: 16px">共 {{ data.timeline.run.total_step }} 步</span>
        <span style="margin-right: 16px">检索 {{ data.timeline.run.retrieve_count }} 次</span>
        <span style="margin-right: 16px">改写 {{ data.timeline.run.rewrite_count }} 次</span>
        <span>耗时 {{ data.timeline.run.cost_millis }} ms</span>
      </div>
      <!-- 每一步一个时间线节点，节点名对应状态图里的节点 -->
      <el-timeline style="max-height: 460px; overflow: auto; padding-left: 6px">
        <el-timeline-item
            v-for="step in data.timeline.steps"
            :key="step.id"
            :type="nodeColor(step.node_name)"
            :timestamp="'第 ' + step.step_index + ' 步 · ' + step.node_name"
        >
          <div style="font-weight: bold; margin-bottom: 4px">{{ step.step_name }}</div>
          <!-- 入参和返回原样展示，看模型每一步到底判断了什么 -->
          <div style="font-size: 12px; color: #666">入参：{{ step.request_params }}</div>
          <div style="font-size: 12px; color: #666">返回：{{ step.response_result }}</div>
          <div v-if="step.error_message" style="font-size: 12px; color: #f56c6c">失败：{{ step.error_message }}</div>
        </el-timeline-item>
      </el-timeline>
      <template #footer>
        <el-button @click="data.timelineVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'
import router from '@/router/index.js'

const data = reactive({
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部运行状态下拉框的值
  runStatus: '',
  // 控制时间线弹窗
  timelineVisible: false,
  timeline: {}
})

const load = () => {
  request.get('/agent/runs', {
    params: { page_num: data.pageNum, page_size: data.pageSize, run_status: data.runStatus }
  }).then(res => {
    if (res.code === '200') {
      data.tableData = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const viewTimeline = (runId) => {
  // 取这次运行的完整步骤，按 step_index 顺序渲染成时间线
  request.get('/agent/steps/' + runId).then(res => {
    if (res.code === '200') {
      data.timeline = res.data
      data.timelineVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const statusColor = (status) => {
  // 已完成绿色、失败红色、运行中蓝色
  if (status === '已完成') {
    return 'success'
  }
  if (status === '运行失败') {
    return 'danger'
  }
  return 'primary'
}

const nodeColor = (node) => {
  // 检索绿色、判断类橙色、兜底红色，扫一眼就知道这次走了哪条路
  if (node === 'retrieve') {
    return 'success'
  }
  if (node === 'grade' || node === 'check') {
    return 'warning'
  }
  if (node === 'fallback') {
    return 'danger'
  }
  return 'primary'
}

const reset = () => {
  data.runStatus = ''
  data.pageNum = 1
  load()
}

// 从 Agent 执行页跳过来时地址栏带着 runId，直接打开那一次的时间线
const runId = router.currentRoute.value.query.runId
load()
if (runId) {
  viewTimeline(runId)
}
</script>
