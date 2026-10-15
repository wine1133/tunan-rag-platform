<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-form label-width="100px" style="padding: 10px 20px 0">
        <!-- 至少选一个知识库，括号里的片段数为 0 说明还没切分 -->
        <el-form-item label="知识库">
          <el-select v-model="data.kbIds" multiple style="width: 100%" placeholder="请选择要检索的知识库" @change="onKbChange">
            <el-option
                v-for="kb in data.kbOptions"
                :key="kb.id"
                :label="kb.name + '（片段 ' + kb.chunk_count + ' 条）'"
                :value="kb.id"
            ></el-option>
          </el-select>
        </el-form-item>
        <!-- 最多选四套，每多一套就多跑一遍完整检索 -->
        <el-form-item label="对比策略">
          <el-select v-model="data.strategyIds" multiple :multiple-limit="4" style="width: 100%" placeholder="最多选择 4 套策略并排对比">
            <el-option
                v-for="item in data.strategyOptions"
                :key="item.id"
                :label="strategyLabel(item)"
                :value="item.id"
            ></el-option>
          </el-select>
        </el-form-item>
        <!-- 限定只在某几篇文档里检索 -->
        <el-form-item label="限定文档">
          <el-select v-model="data.documentIds" multiple clearable style="width: 100%" placeholder="不选表示在整个知识库里检索">
            <el-option v-for="doc in data.docOptions" :key="doc.id" :label="doc.name" :value="doc.id"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="检索问题">
          <el-input v-model="data.query" type="textarea" :rows="2" placeholder="输入一个用户可能会问的问题"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="data.running" @click="compare">开始对比</el-button>
          <!-- 这个库的片段类型分布，用来判断要不要开父块回填 -->
          <span v-if="data.chunkTypes.parent > 0" style="margin-left: 16px; color: #999; font-size: 12px">
            该库是父子分块（父块 {{ data.chunkTypes.parent }} 条 / 子块 {{ data.chunkTypes.child }} 条），建议开启父块回填对比
          </span>
        </el-form-item>
      </el-form>
    </div>

    <!-- 每套策略一列并排展示，列数等于选中的策略数 -->
    <el-row :gutter="10" v-if="data.columns.length">
      <el-col :span="24 / data.columns.length" v-for="column in data.columns" :key="column.strategy_id">
        <div class="card" style="margin-bottom: 5px">
          <div style="font-weight: bold; padding-bottom: 6px">{{ column.strategy_name }}</div>
          <!-- 某套策略跑失败时这一列显示失败原因，其他列照常展示 -->
          <el-alert v-if="column.error" :title="column.error" type="error" :closable="false" style="margin-bottom: 8px" />
          <div style="color: #666; font-size: 12px; padding-bottom: 6px">
            召回 {{ column.results.length }} 条 · 耗时 {{ column.cost_millis }} ms
          </div>
          <!-- 每套策略的最终分数量纲可能不同，不标出来的话，
               左边一列的 0.03（RRF 名次分）会被当成比右边一列的 0.19（重排相关分）更差 -->
          <div v-if="column.score_scale" style="font-size: 12px; padding-bottom: 6px">
            <el-tag size="small" type="info">分数量纲：{{ column.score_scale }}</el-tag>
          </div>
          <!-- 各阶段耗时，能看出这套策略慢在哪一步 -->
          <el-table :data="column.stages" size="small" style="margin-bottom: 8px">
            <el-table-column prop="name" label="阶段" />
            <el-table-column prop="count" label="条数" width="90" />
            <el-table-column prop="cost_millis" label="ms" width="70" />
          </el-table>
          <!-- 召回结果按名次从上到下，同一行对比几列就能看出排序差异 -->
          <el-table :data="column.results" size="small">
            <el-table-column type="index" label="#" width="45" />
            <!-- 表头带上本列的量纲，跨列比分数前先看清楚两列是不是同一把尺子 -->
            <el-table-column prop="score" :label="column.score_scale || '分数'" width="110" />
            <el-table-column prop="content" label="片段" show-overflow-tooltip />
          </el-table>
        </div>
      </el-col>
    </el-row>

    <div class="card" v-if="data.records.length">
      <div style="font-weight: bold; padding-bottom: 8px">历史调试记录</div>
      <!-- 每次对比都会存档，点查看能把当时的召回结果原样调出来 -->
      <el-table stripe :data="data.records" size="small">
        <el-table-column prop="query" label="问题" show-overflow-tooltip />
        <el-table-column prop="strategy_ids" label="对比策略" width="140" />
        <el-table-column prop="cost_millis" label="耗时（ms）" width="110" />
        <el-table-column prop="create_time" label="时间" width="180" />
        <el-table-column label="操作" width="90">
          <template #default="scope">
            <el-button type="primary" size="small" @click="viewRecord(scope.row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 知识库下拉选项，来自 /retrieval/knowledgeBases
  kbOptions: [],
  // 检索策略下拉选项，来自 /retrieval/strategies
  strategyOptions: [],
  // 文档下拉选项，随知识库联动
  docOptions: [],
  // 选中的知识库、策略、文档
  kbIds: [],
  strategyIds: [],
  documentIds: [],
  // 检索问题
  query: '',
  // 对比按钮的转圈状态，几套策略串行跑，耗时是单套的几倍
  running: false,
  // 每套策略一列，来自 /retrievalStrategy/compare 返回的 columns
  columns: [],
  // 这个库的片段类型分布
  chunkTypes: {},
  // 历史调试记录列表
  records: []
})

const loadOptions = () => {
  request.get('/retrieval/knowledgeBases').then(res => {
    if (res.code === '200') {
      data.kbOptions = res.data || []
    }
  })
  request.get('/retrieval/strategies').then(res => {
    if (res.code === '200') {
      data.strategyOptions = res.data || []
    }
  })
}

const loadRecords = () => {
  // 列表接口不返回快照正文，只有点查看时才把完整快照取回来
  request.get('/retrievalStrategy/records', {
    params: { page_num: 1, page_size: 10 }
  }).then(res => {
    if (res.code === '200') {
      data.records = res.data?.list || []
    }
  })
}

const onKbChange = () => {
  // 换了知识库，原来选中的文档可能已经不属于这些库了，清空重取
  data.documentIds = []
  data.docOptions = []
  data.chunkTypes = {}
  if (!data.kbIds.length) {
    return
  }
  Promise.all(
      data.kbIds.map(kbId => request.get('/knowledgeDocument/selectPage', {
        params: { kb_id: kbId, page_num: 1, page_size: 200 }
      }))
  ).then(responses => {
    const merged = []
    responses.forEach(res => {
      if (res.code === '200') {
        merged.push(...(res.data?.list || []))
      }
    })
    data.docOptions = merged
  })
  // 取第一个库的片段类型分布做提示
  request.get('/retrievalStrategy/chunkTypes/' + data.kbIds[0]).then(res => {
    if (res.code === '200') {
      data.chunkTypes = res.data || {}
    }
  })
}

const strategyLabel = (item) => {
  // 把这套策略开了哪几步拼进选项文字，选的时候不用切页面去看配置
  const parts = []
  if (item.vector_enabled === '是') {
    parts.push('向量')
  }
  if (item.bm25_enabled === '是') {
    parts.push('BM25')
  }
  if (item.rerank_enabled === '是') {
    parts.push('重排')
  }
  if (item.query_rewrite_enabled === '是') {
    parts.push(item.rewrite_type)
  }
  if (item.parent_recall_enabled === '是') {
    parts.push('父块回填')
  }
  return item.name + '（' + parts.join('+') + '）'
}

const compare = () => {
  if (!data.kbIds.length) {
    ElMessage.warning('请选择知识库')
    return
  }
  if (!data.strategyIds.length) {
    ElMessage.warning('请至少选择一套策略')
    return
  }
  if (!data.query.trim()) {
    ElMessage.warning('请输入检索问题')
    return
  }
  data.running = true
  request.post('/retrievalStrategy/compare', {
    kb_ids: data.kbIds,
    strategy_ids: data.strategyIds,
    document_ids: data.documentIds.length ? data.documentIds : null,
    query: data.query
  }).then(res => {
    if (res.code === '200') {
      // columns 里每一项是一套策略的完整检索结果
      data.columns = res.data.columns || []
      // 这次对比已经存档，刷新一下历史列表
      loadRecords()
    } else {
      ElMessage.error(res.msg)
    }
  }).finally(() => {
    data.running = false
  })
}

const viewRecord = (id) => {
  // 把存档的快照原样调出来，覆盖当前的对比结果
  request.get('/retrievalStrategy/records/' + id).then(res => {
    if (res.code === '200') {
      data.query = res.data.query
      data.columns = res.data.columns || []
    } else {
      ElMessage.error(res.msg)
    }
  })
}

// 页面加载时取下拉数据和历史记录
loadOptions()
loadRecords()
</script>
