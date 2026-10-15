<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 同一个评测集下的报告才有可比性，先选评测集 -->
      <el-select v-model="data.datasetId" clearable style="width: 260px; margin-right: 10px" placeholder="按评测集筛选" @change="loadReports">
        <el-option
            v-for="item in data.datasets"
            :key="item.id"
            :label="item.name"
            :value="item.id"
        ></el-option>
      </el-select>
      <el-button type="primary" @click="compare">对比选中的报告</el-button>
      <span style="margin-left: 12px; color: #999; font-size: 12px">在表格里勾选两份以上的报告</span>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- 勾选两份以上再点对比 -->
      <el-table stripe :data="data.reports" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" />
        <el-table-column prop="strategy_name" label="策略" width="220" />
        <!-- 这套策略开了哪几步，从策略快照里读出来 -->
        <el-table-column label="启用的能力" min-width="220">
          <template #default="scope">
            <el-tag v-for="item in scope.row.abilities" :key="item" size="small" style="margin-right: 4px">{{ item }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="case_count" label="用例" width="80" />
        <el-table-column prop="context_recall_avg" label="召回" width="90" />
        <el-table-column prop="context_precision_avg" label="精度" width="90" />
        <el-table-column prop="faithfulness_avg" label="忠实度" width="90" />
        <el-table-column prop="answer_relevancy_avg" label="相关性" width="90" />
        <el-table-column prop="overall_score" label="综合" width="90" />
        <!-- 第 26 章说过：对比表里必须有耗时，否则没法谈取舍 -->
        <el-table-column prop="avg_cost_millis" label="单条耗时（ms）" width="130">
          <template #default="scope">{{ scope.row.avg_cost_millis ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="create_time" label="时间" width="180" />
      </el-table>
    </div>

    <!-- 对比结果：分组柱状图 + 明细表 -->
    <div class="card" v-if="data.compare.columns">
      <div style="font-weight: bold; padding-bottom: 10px">
        {{ data.compare.dataset_name }} · {{ data.compare.columns.length }} 套策略对比
      </div>
      <div ref="chartRef" style="height: 340px"></div>
      <el-table stripe :data="tableRows" size="small" style="margin-top: 10px">
        <el-table-column prop="metric" label="指标" width="140" />
        <el-table-column
            v-for="(column, index) in data.compare.columns"
            :key="column.report_id"
            :label="column.strategy_name"
        >
          <template #default="scope">{{ scope.row.values[index] ?? '—' }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, reactive, ref } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'

const chartRef = ref()

const data = reactive({
  datasets: [],
  datasetId: '',
  reports: [],
  // 表格里勾选的报告 ID
  selectedIds: [],
  // 对比结果，含 columns 和 series
  compare: {},

})

// 图表下方的明细表：每个指标一行，各策略的分数排成一列
const tableRows = computed(() => {
  if (!data.compare.series) {
    return []
  }
  return data.compare.series.map(item => ({ metric: item.metric, values: item.values }))
})

const loadDatasets = () => {
  request.get('/evalDataset/selectAll').then(res => {
    if (res.code === '200') {
      data.datasets = res.data || []
    }
  })
}

const loadReports = () => {
  request.get('/evalReport/selectAll', {
    params: { dataset_id: data.datasetId || undefined }
  }).then(res => {
    if (res.code === '200') {
      data.reports = res.data || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleSelectionChange = (rows) => {
  data.selectedIds = rows.map(item => item.id)
}

const compare = () => {
  if (data.selectedIds.length < 2) {
    ElMessage.warning('请至少勾选两份报告')
    return
  }
  request.post('/evalReport/compare', { report_ids: data.selectedIds }).then(res => {
    if (res.code === '200') {
      data.compare = res.data
      // 等表格和容器渲染完再画图，否则图表拿不到高度
      nextTick(renderChart)
    } else {
      // 只选一份、跨评测集对比，后端都返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const renderChart = () => {
  if (!chartRef.value || !data.compare.series) {
    return
  }
  // 同一个容器重复画图前先销毁上一个实例，否则会叠加
  const existing = echarts.getInstanceByDom(chartRef.value)
  if (existing) {
    existing.dispose()
  }
  const chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: data.compare.columns.map(item => item.strategy_name) },
    grid: { left: 50, right: 20, top: 50, bottom: 30 },
    // 四个指标作为横轴分类，每套策略一组柱子
    xAxis: { type: 'category', data: data.compare.series.map(item => item.metric) },
    // 四个指标取值都是 0 到 1，纵轴固定范围，不同次对比之间也能直观比较
    yAxis: { type: 'value', min: 0, max: 1 },
    series: data.compare.columns.map((column, index) => ({
      name: column.strategy_name,
      type: 'bar',
      data: data.compare.series.map(item => item.values[index])
    }))
  })
}

loadDatasets()
loadReports()
</script>
