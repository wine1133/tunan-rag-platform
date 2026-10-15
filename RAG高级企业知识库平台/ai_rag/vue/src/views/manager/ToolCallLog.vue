<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 按工具编码筛选，看某个工具的历史调用情况 -->
      <el-select v-model="data.toolCode" clearable style="width: 200px; margin-right: 10px" placeholder="请选择工具">
        <el-option v-for="item in data.toolOptions" :key="item.tool_code" :label="item.tool_name" :value="item.tool_code"></el-option>
      </el-select>
      <!-- 只看失败的调用，排查问题时最常用 -->
      <el-select v-model="data.callStatus" clearable style="width: 140px; margin-right: 10px" placeholder="调用结果">
        <el-option label="成功" value="成功"></el-option>
        <el-option label="失败" value="失败"></el-option>
      </el-select>
      <!-- 按运行编号筛，看某一次 Agent 运行调了哪些工具 -->
      <el-input v-model="data.runId" style="width: 160px; margin-right: 10px" placeholder="按运行ID筛选"></el-input>
      <el-button type="info" plain @click="load">查询</el-button>
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /functionTool/logs 返回的 list -->
      <el-table stripe :data="data.tableData">
        <el-table-column prop="id" label="日志ID" width="90" />
        <el-table-column prop="run_id" label="运行ID" width="90">
          <template #default="scope">{{ scope.row.run_id || '-' }}</template>
        </el-table-column>
        <el-table-column prop="tool_name" label="工具" width="150" />
        <!-- 成功绿色、失败红色，一眼扫出哪些调用出了问题 -->
        <el-table-column prop="call_status" label="结果" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.call_status === '成功' ? 'success' : 'danger'" size="small">{{ scope.row.call_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="request_params" label="入参" show-overflow-tooltip />
        <el-table-column prop="error_message" label="失败原因" show-overflow-tooltip />
        <el-table-column prop="cost_millis" label="耗时（ms）" width="110" />
        <el-table-column prop="create_time" label="时间" width="180" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="scope">
            <el-button type="primary" size="small" @click="viewDetail(scope.row)">详情</el-button>
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

    <!-- 详情弹窗：完整的入参和返回，排查工具执行问题时看这里 -->
    <el-dialog title="调用详情" v-model="data.detailVisible" width="60%" destroy-on-close>
      <div style="margin-bottom: 6px; font-weight: bold">入参</div>
      <div style="background: #f7f7f7; padding: 10px; white-space: pre-wrap; font-size: 13px; margin-bottom: 12px">{{ data.detail.request_params || '无' }}</div>
      <div style="margin-bottom: 6px; font-weight: bold">返回</div>
      <div style="max-height: 320px; overflow: auto; background: #f7f7f7; padding: 10px; white-space: pre-wrap; font-size: 13px">{{ data.detail.response_result || data.detail.error_message || '无' }}</div>
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

const data = reactive({
  tableData: [],
  // 工具下拉选项，来自 /functionTool/logSummary
  toolOptions: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 三个筛选条件
  toolCode: '',
  callStatus: '',
  runId: '',
  // 控制详情弹窗
  detailVisible: false,
  detail: {}
})

const loadTools = () => {
  // 统计接口顺带返回了工具清单，下拉框直接用它
  request.get('/functionTool/logSummary').then(res => {
    if (res.code === '200') {
      data.toolOptions = res.data || []
    }
  })
}

const load = () => {
  request.get('/functionTool/logs', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      tool_code: data.toolCode,
      call_status: data.callStatus,
      run_id: data.runId || undefined
    }
  }).then(res => {
    if (res.code === '200') {
      data.tableData = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const viewDetail = (row) => {
  // 列表里入参和返回都被截断显示，详情弹窗看完整内容
  data.detail = row
  data.detailVisible = true
}

const reset = () => {
  data.toolCode = ''
  data.callStatus = ''
  data.runId = ''
  data.pageNum = 1
  load()
}

// 页面加载时取工具下拉数据并查第一页日志
loadTools()
load()
</script>
