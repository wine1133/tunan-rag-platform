<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 先选评测集，下方的用例列表跟着变 -->
      <el-select v-model="data.datasetId" style="width: 280px; margin-right: 10px" placeholder="请选择评测集" @change="loadCases">
        <el-option
            v-for="item in data.datasets"
            :key="item.id"
            :label="item.name + '（' + item.case_count + ' 条用例）'"
            :value="item.id"
        ></el-option>
      </el-select>
      <el-button type="primary" plain @click="handleAddDataset">新建评测集</el-button>
      <el-button type="danger" plain :disabled="!data.datasetId" @click="delDataset">删除评测集</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px" v-if="data.datasetId">
      <!-- 三个来源对应三个入口 -->
      <el-button type="primary" plain @click="handleAddCase">手工录入</el-button>
      <el-button type="success" plain @click="data.generateVisible = true">从文档自动生成</el-button>
      <el-button type="warning" plain @click="convertFeedback">从点踩沉淀</el-button>
      <el-select v-model="data.source" clearable style="width: 160px; margin: 0 10px" placeholder="按来源筛选" @change="loadCases">
        <el-option label="手工录入" value="手工录入"></el-option>
        <el-option label="文档生成" value="文档生成"></el-option>
        <el-option label="反馈沉淀" value="反馈沉淀"></el-option>
      </el-select>
      <el-input v-model="data.keyword" style="width: 200px; margin-right: 10px" placeholder="按问题搜索"></el-input>
      <el-button type="info" plain @click="loadCases">查询</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px" v-if="data.datasetId">
      <el-table stripe :data="data.cases">
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <!-- 反馈沉淀出来的用例这一列是空的，要人工补 -->
        <el-table-column prop="ground_truth" label="标准答案" min-width="200" show-overflow-tooltip>
          <template #default="scope">
            <span v-if="scope.row.ground_truth">{{ scope.row.ground_truth }}</span>
            <el-tag v-else type="warning" size="small">待补充</el-tag>
          </template>
        </el-table-column>
        <!-- 三个来源用不同颜色区分 -->
        <el-table-column prop="source" label="来源" width="110">
          <template #default="scope">
            <el-tag :type="sourceColor(scope.row.source)" size="small">{{ scope.row.source }}</el-tag>
          </template>
        </el-table-column>
        <!-- 停用的用例不参与评测，标准答案没补完的默认就是停用 -->
        <el-table-column prop="enabled" label="参与评测" width="100">
          <template #default="scope">
            <el-tag :type="scope.row.enabled === '是' ? 'success' : 'info'" size="small">{{ scope.row.enabled }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="scope">
            <!-- 标准答案是模型照着片段生成的，可能看错段或张冠李戴。
                 把片段原文调出来，才能判断这条标准答案能不能当基准用 -->
            <el-button
                type="success" size="small"
                :disabled="!scope.row.reference_chunk_ids"
                @click="viewChunks(scope.row)"
            >看原文</el-button>
            <el-button type="primary" size="small" @click="handleEditCase(scope.row)">编辑</el-button>
            <el-button type="danger" size="small" @click="delCase(scope.row.id)">删除</el-button>
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
          @current-change="loadCases"
      />
    </div>

    <!-- 新建评测集弹窗 -->
    <el-dialog title="新建评测集" v-model="data.datasetVisible" width="40%" destroy-on-close>
      <el-form :model="data.datasetForm" label-width="100px" style="padding: 10px 20px">
        <el-form-item label="评测集名称">
          <el-input v-model="data.datasetForm.name" placeholder="例如：产品手册库-基线评测集"></el-input>
        </el-form-item>
        <el-form-item label="关联知识库">
          <el-select v-model="data.datasetForm.kb_id" clearable style="width: 100%" placeholder="这个评测集针对哪个知识库">
            <el-option v-for="kb in data.kbOptions" :key="kb.id" :label="kb.name" :value="kb.id"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="data.datasetForm.description" type="textarea" :rows="2"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.datasetVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDataset">确定</el-button>
      </template>
    </el-dialog>

    <!-- 用例弹窗，手工录入和编辑共用 -->
    <el-dialog title="评测用例" v-model="data.caseVisible" width="50%" destroy-on-close>
      <el-form :model="data.caseForm" label-width="100px" style="padding: 10px 20px">
        <el-form-item label="问题">
          <el-input v-model="data.caseForm.question" type="textarea" :rows="2" placeholder="用户可能会这样问"></el-input>
        </el-form-item>
        <!-- 没有标准答案就算不了上下文召回，后端会拦住 -->
        <el-form-item label="标准答案">
          <el-input v-model="data.caseForm.ground_truth" type="textarea" :rows="4" placeholder="这个问题正确的答案是什么"></el-input>
        </el-form-item>
        <el-form-item label="参与评测">
          <el-radio-group v-model="data.caseForm.enabled">
            <el-radio value="是">是</el-radio>
            <el-radio value="否">否</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="data.caseForm.remark"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.caseVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCase">确定</el-button>
      </template>
    </el-dialog>

    <!-- 自动生成弹窗 -->
    <el-dialog title="从文档自动生成用例" v-model="data.generateVisible" width="45%" destroy-on-close>
      <el-form label-width="100px" style="padding: 10px 20px">
        <el-form-item label="知识库">
          <el-select v-model="data.genKbId" style="width: 100%" placeholder="请选择知识库" @change="loadDocs">
            <el-option v-for="kb in data.kbOptions" :key="kb.id" :label="kb.name" :value="kb.id"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="文档">
          <el-select v-model="data.genDocId" style="width: 100%" placeholder="模型会读这篇文档的片段生成问答对">
            <el-option v-for="doc in data.docOptions" :key="doc.id" :label="doc.name" :value="doc.id"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="生成条数">
          <el-input-number v-model="data.genCount" :min="1" :max="20" style="width: 100%"></el-input-number>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.generateVisible = false">取消</el-button>
        <el-button type="primary" :loading="data.generating" @click="generate">开始生成</el-button>
      </template>
    </el-dialog>

    <!-- 来源片段原文：问题、标准答案、原文三样摆一起，一眼判断标准答案对不对 -->
    <el-dialog title="核对标准答案" v-model="data.chunkVisible" width="60%" destroy-on-close>
      <div style="margin-bottom: 12px">
        <div style="color: #666; font-size: 13px; margin-bottom: 4px">问题</div>
        <div>{{ data.chunkCase.question }}</div>
      </div>
      <div style="margin-bottom: 12px">
        <div style="color: #666; font-size: 13px; margin-bottom: 4px">标准答案</div>
        <div style="font-weight: bold">{{ data.chunkCase.ground_truth || '（未填）' }}</div>
      </div>
      <div style="color: #666; font-size: 13px; margin-bottom: 4px">
        来源片段原文（模型就是照着这段出的题，对不上说明这条标准答案不能用）
      </div>
      <div v-if="!data.chunks.length" style="color: #999">这条用例没有记录来源片段</div>
      <div
          v-for="chunk in data.chunks" :key="chunk.chunk_id"
          style="background: #f7f7f7; border-radius: 4px; padding: 10px; margin-bottom: 8px"
      >
        <div style="color: #999; font-size: 12px; margin-bottom: 6px">
          片段 #{{ chunk.chunk_id }} · 第 {{ chunk.chunk_index }} 段
          <span v-if="chunk.page_no">· 第 {{ chunk.page_no }} 页</span>
        </div>
        <div style="white-space: pre-wrap; line-height: 1.7">{{ chunk.content }}</div>
      </div>
      <template #footer>
        <el-button @click="data.chunkVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 核对标准答案的弹窗：当前看的是哪条用例、它的来源片段原文
  chunkVisible: false,
  chunkCase: {},
  chunks: [],
  datasets: [],
  datasetId: '',
  cases: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  source: '',
  keyword: '',
  // 知识库和文档两份下拉数据
  kbOptions: [],
  docOptions: [],
  // 三个弹窗
  datasetVisible: false,
  datasetForm: {},
  caseVisible: false,
  caseForm: {},
  generateVisible: false,
  genKbId: '',
  genDocId: '',
  genCount: 5,
  generating: false
})

const loadDatasets = () => {
  request.get('/evalDataset/selectAll').then(res => {
    if (res.code === '200') {
      data.datasets = res.data || []
      // 没选过评测集时默认选第一个，进页面就有内容
      if (!data.datasetId && data.datasets.length) {
        data.datasetId = data.datasets[0].id
        loadCases()
      }
    }
  })
}

const loadKbs = () => {
  request.get('/knowledgeBase/selectAll').then(res => {
    if (res.code === '200') {
      data.kbOptions = res.data || []
    }
  })
}

const loadDocs = () => {
  data.genDocId = ''
  if (!data.genKbId) {
    data.docOptions = []
    return
  }
  request.get('/knowledgeDocument/selectPage', {
    params: { kb_id: data.genKbId, page_num: 1, page_size: 200 }
  }).then(res => {
    if (res.code === '200') {
      data.docOptions = res.data?.list || []
    }
  })
}

const loadCases = () => {
  if (!data.datasetId) {
    return
  }
  request.get('/evalDataset/case/selectPage', {
    params: {
      dataset_id: data.datasetId,
      source: data.source,
      keyword: data.keyword,
      page_num: data.pageNum,
      page_size: data.pageSize
    }
  }).then(res => {
    if (res.code === '200') {
      data.cases = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleAddDataset = () => {
  data.datasetForm = {}
  data.datasetVisible = true
}

const saveDataset = () => {
  request.post('/evalDataset/add', data.datasetForm).then(res => {
    if (res.code === '200') {
      ElMessage.success('保存成功')
      data.datasetVisible = false
      loadDatasets()
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const delDataset = () => {
  ElMessageBox.confirm('删除评测集会连同它的用例一起删除，确定吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/evalDataset/delete/' + data.datasetId).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        data.datasetId = ''
        data.cases = []
        data.total = 0
        loadDatasets()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const handleAddCase = () => {
  // 手工录入的用例默认启用，标准答案当场就填了
  data.caseForm = { dataset_id: data.datasetId, source: '手工录入', enabled: '是' }
  data.caseVisible = true
}

const viewChunks = (row) => {
  // 把这条用例本身先摆上，再去取它的来源片段原文
  data.chunkCase = row
  data.chunks = []
  data.chunkVisible = true
  request.get('/evalDataset/case/referenceChunks/' + row.id).then(res => {
    if (res.code === '200') {
      data.chunks = res.data
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleEditCase = (row) => {
  data.caseForm = JSON.parse(JSON.stringify(row))
  data.caseVisible = true
}

const saveCase = () => {
  const action = data.caseForm.id
      ? request.put('/evalDataset/case/update', data.caseForm)
      : request.post('/evalDataset/case/add', data.caseForm)
  action.then(res => {
    if (res.code === '200') {
      ElMessage.success('保存成功')
      data.caseVisible = false
      loadCases()
      loadDatasets()
    } else {
      // 没填标准答案时后端会拦住
      ElMessage.error(res.msg)
    }
  })
}

const delCase = (id) => {
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/evalDataset/case/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        loadCases()
        loadDatasets()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const generate = () => {
  if (!data.genDocId) {
    ElMessage.warning('请选择文档')
    return
  }
  data.generating = true
  request.post('/evalDataset/generate', {
    dataset_id: data.datasetId,
    document_id: data.genDocId,
    count: data.genCount
  }).then(res => {
    if (res.code === '200') {
      // res.data 里带着生成了多少条
      ElMessage.success(res.data)
      data.generateVisible = false
      loadCases()
      loadDatasets()
    } else {
      // 文档没切分、模型没返回可用 JSON，后端都返回人话提示
      ElMessage.error(res.msg)
    }
  }).finally(() => {
    data.generating = false
  })
}

const convertFeedback = () => {
  ElMessageBox.confirm('会把所有待沉淀的点踩问题转成用例，标准答案需要你手工补充，继续吗？', '沉淀确认', { type: 'warning' }).then(() => {
    request.post('/evalDataset/convert', { dataset_id: data.datasetId }).then(res => {
      if (res.code === '200') {
        ElMessage.success(res.data)
        loadCases()
        loadDatasets()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const sourceColor = (source) => {
  // 手工录入蓝色、文档生成绿色、反馈沉淀橙色
  if (source === '手工录入') {
    return 'primary'
  }
  if (source === '文档生成') {
    return 'success'
  }
  return 'warning'
}

loadDatasets()
loadKbs()
</script>
