<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-form label-width="90px" style="padding: 10px 20px 0">
        <!-- 至少选一个知识库，括号里的片段数为 0 说明还没切分，检索不出东西 -->
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
        <!-- 限定只在某几篇文档里检索。库里同时有新旧两版制度时，用它把范围缩到新版那篇 -->
        <el-form-item label="限定文档">
          <el-select v-model="data.documentIds" multiple clearable style="width: 100%" placeholder="不选表示在整个知识库里检索">
            <el-option v-for="doc in data.docOptions" :key="doc.id" :label="doc.name" :value="doc.id"></el-option>
          </el-select>
        </el-form-item>
        <!-- 不选时后端用默认策略，选项文字里带出这套策略开了哪几路 -->
        <el-form-item label="检索策略">
          <el-select v-model="data.strategyId" clearable style="width: 100%" placeholder="不选则使用默认策略">
            <el-option
                v-for="item in data.strategyOptions"
                :key="item.id"
                :label="strategyLabel(item)"
                :value="item.id"
            ></el-option>
          </el-select>
        </el-form-item>
        <!-- 输入的问题存进 data.query，作为 query 参数发给检索接口 -->
        <el-form-item label="检索问题">
          <el-input v-model="data.query" type="textarea" :rows="2" placeholder="输入一个用户可能会问的问题"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="data.searching" @click="search">开始检索</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 有结果才显示这一块，进页面时是空的 -->
    <div class="card" style="margin-bottom: 5px" v-if="data.outcome.strategy_name">
      <div style="padding: 10px 0">
        <span style="margin-right: 20px">使用策略：{{ data.outcome.strategy_name }}</span>
        <span style="margin-right: 20px">召回 {{ data.outcome.results.length }} 条</span>
        <span style="margin-right: 20px">总耗时 {{ data.outcome.cost_millis }} ms</span>
        <!-- 分数量纲由后端按管线末端给出，同一列数字在不同策略下含义不同 -->
        <span v-if="data.outcome.score_scale">分数量纲：{{ data.outcome.score_scale }}</span>
      </div>
      <!-- 每一路召回了多少条、各花了多久，用来判断瓶颈在哪一步 -->
      <el-table stripe :data="data.outcome.stages" size="small" style="margin-bottom: 10px">
        <el-table-column prop="name" label="阶段" width="200" />
        <el-table-column prop="count" label="条数" width="120" />
        <el-table-column prop="cost_millis" label="耗时（ms）" width="120" />
        <!-- 查询改写阶段会把改写出来的查询放在 detail 里 -->
        <el-table-column label="明细">
          <template #default="scope">
            <div v-for="(line, index) in scope.row.detail" :key="index">{{ line }}</div>
          </template>
        </el-table-column>
      </el-table>
      <!-- 开了改写时，实际拿去检索的问题和用户输入的不一样，单独列出来 -->
      <div v-if="data.outcome.queries && data.outcome.queries.length > 1" style="padding-bottom: 10px">
        <div style="margin-bottom: 4px">实际用于检索的问题（共 {{ data.outcome.queries.length }} 条）：</div>
        <el-tag v-for="(one, index) in data.outcome.queries" :key="index" size="small" style="margin: 0 6px 6px 0">{{ one }}</el-tag>
      </div>
    </div>

    <div class="card" v-if="data.outcome.results && data.outcome.results.length">
      <!-- 召回结果按最终排名从上到下展示 -->
      <el-table stripe :data="data.outcome.results">
        <!-- 名次就是行号，第 13 章讲的"该看的那段排在第 4 位"看的就是这一列 -->
        <el-table-column type="index" label="名次" width="70" />
        <!-- 两路都召回的结果这里会显示"BM25检索+向量检索" -->
        <el-table-column prop="source" label="召回来源" width="160" />
        <!-- 表头带上量纲：向量单路是余弦相似度，融合后是 RRF 名次分，重排后是重排相关分 -->
        <el-table-column prop="score" :label="data.outcome.score_scale || '分数'" width="120" />
        <el-table-column prop="document_name" label="来源文档" width="180" show-overflow-tooltip />
        <el-table-column prop="chunk_type" label="类型" width="90" />
        <!-- 开了父块回填时，这一列显示实际命中的是哪个子块，能追溯到匹配的那一小段 -->
        <el-table-column prop="matched_chunk_id" label="命中子块" width="100">
          <template #default="scope">{{ scope.row.matched_chunk_id || '-' }}</template>
        </el-table-column>
        <el-table-column prop="content" label="片段内容" show-overflow-tooltip />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 知识库下拉选项，来自 /retrieval/knowledgeBases，带片段数
  kbOptions: [],
  // 检索策略下拉选项，来自 /retrieval/strategies
  strategyOptions: [],
  // 选中的知识库 id 数组，可以多选，跨库检索
  kbIds: [],
  // 文档下拉选项，随选中的知识库变化
  docOptions: [],
  // 选中的文档 id 数组，为空表示不限定文档
  documentIds: [],
  // 选中的策略 id，为空表示让后端用默认策略
  strategyId: '',
  // 检索问题
  query: '',
  // 检索按钮的转圈状态，向量检索要调模型，慢的时候有几百毫秒
  searching: false,
  // 检索结果，含 results、stages、cost_millis
  outcome: {}
})

const loadOptions = () => {
  // 知识库下拉带上片段数，片段为 0 的库检索不出东西，选之前就能看出来
  request.get('/retrieval/knowledgeBases').then(res => {
    if (res.code === '200') {
      data.kbOptions = res.data || []
    }
  })
  // 策略下拉，选项文字里把开关情况写出来，不用切页面去看配置
  request.get('/retrieval/strategies').then(res => {
    if (res.code === '200') {
      data.strategyOptions = res.data || []
    }
  })
}

const onKbChange = () => {
  // 换了知识库，原来选中的文档可能已经不属于这些库了，清空重取
  data.documentIds = []
  data.docOptions = []
  if (!data.kbIds.length) {
    return
  }
  // 每个库各取一次文档列表，合并成一份下拉数据
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
}

const strategyLabel = (item) => {
  // 把这套策略开了哪几路拼进选项文字，例如"完整-混合检索加重排加改写（向量+BM25）"
  const parts = []
  if (item.vector_enabled === '是') {
    parts.push('向量')
  }
  if (item.bm25_enabled === '是') {
    parts.push('BM25')
  }
  return item.name + '（' + parts.join('+') + '）'
}

const emptyReason = (outcome) => {
  // 0 条结果有两种完全不同的原因，提示语必须分开，不然会把人引到错的地方去查。
  // 阈值过滤那一步的 count 形如 "4 → 0"，箭头前不是 0 就说明片段召回到了，
  // 是被阈值卡掉的，这时候该调的是策略里的阈值，不是去查知识库有没有切分
  const filtered = (outcome.stages || []).find(
      stage => stage.name.startsWith('阈值过滤') && / → 0$/.test(String(stage.count)) && !/^0 →/.test(String(stage.count))
  )
  if (filtered) {
    // 后端在 detail 里写清了本次分数区间和门槛，直接把最后一句结论拿来提示
    const lines = filtered.detail || []
    return lines[lines.length - 1] || '召回的片段全部低于阈值，请调低这套策略的阈值'
  }
  return '没有召回到任何片段，检查这个库是否已经向量化或切分'
}

const search = () => {
  // 一个知识库都没选时前端直接拦住，不发请求
  if (!data.kbIds.length) {
    ElMessage.warning('请选择知识库')
    return
  }
  if (!data.query.trim()) {
    ElMessage.warning('请输入检索问题')
    return
  }
  data.searching = true
  request.post('/retrieval/search', {
    kb_ids: data.kbIds,
    strategy_id: data.strategyId || null,
    // 为空时传 null，后端按不限定文档处理
    document_ids: data.documentIds.length ? data.documentIds : null,
    query: data.query
  }).then(res => {
    if (res.code === '200') {
      // res.data 里有 results 召回结果、stages 各阶段耗时、score_scale 分数量纲、cost_millis 总耗时
      // res.data 里有 results 召回结果、stages 各阶段耗时、cost_millis 总耗时
      data.outcome = res.data
      if (!res.data.results.length) {
        ElMessage.warning(emptyReason(res.data))
      }
    } else {
      // 没配向量模型、向量库连不上、策略一路都没开，后端都返回人话提示
      ElMessage.error(res.msg)
    }
  }).finally(() => {
    data.searching = false
  })
}

// 页面加载时取两份下拉数据
loadOptions()
</script>
