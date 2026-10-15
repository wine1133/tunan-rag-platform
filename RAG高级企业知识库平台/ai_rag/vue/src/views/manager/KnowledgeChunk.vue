<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 先选知识库，文档下拉框跟着只列这个库下的文档 -->
      <el-select v-model="data.kbId" clearable style="width: 180px; margin-right: 10px" placeholder="请选择知识库" @change="onKbChange">
        <el-option v-for="kb in data.kbOptions" :key="kb.id" :label="kb.name" :value="kb.id"></el-option>
      </el-select>
      <!-- 选中的文档 id 存进 data.documentId，作为 document_id 参数限定查询范围 -->
      <el-select v-model="data.documentId" clearable style="width: 200px; margin-right: 10px" placeholder="请选择文档">
        <el-option v-for="doc in data.docOptions" :key="doc.id" :label="doc.name" :value="doc.id"></el-option>
      </el-select>
      <!-- 父子分块的文档可以只看子块或只看父块 -->
      <el-select v-model="data.chunkType" clearable style="width: 140px; margin-right: 10px" placeholder="片段类型">
        <el-option label="普通块" value="普通块"></el-option>
        <el-option label="父块" value="父块"></el-option>
        <el-option label="子块" value="子块"></el-option>
      </el-select>
      <!-- 在片段正文里模糊匹配，用来定位某句话被切到了哪一段 -->
      <el-input v-model="data.keyword" style="width: 200px; margin-right: 10px" placeholder="在片段内容中搜索"></el-input>
      <!-- 直接调 load，带上当前四个搜索条件重新查询 -->
      <el-button type="info" plain @click="load">查询</el-button>
      <!-- 清空搜索条件并回到第一页 -->
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 删除表格里勾选中的多行 -->
      <el-button type="danger" plain @click="delBatch">批量删除</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /knowledgeChunk/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData" @selection-change="handleSelectionChange">
        <!-- 多选列，配合批量删除使用 -->
        <el-table-column type="selection" width="55" />
        <el-table-column prop="chunk_index" label="序号" width="70" />
        <!-- 父块只做上下文回填不参与检索，用不同颜色区分 -->
        <el-table-column prop="chunk_type" label="类型" width="90">
          <template #default="scope">
            <el-tag :type="chunkTypeColor(scope.row.chunk_type)" size="small">{{ scope.row.chunk_type }}</el-tag>
          </template>
        </el-table-column>
        <!-- 片段正文，过长时省略，点查看按钮看全文 -->
        <el-table-column prop="content" label="片段内容" show-overflow-tooltip />
        <el-table-column prop="char_count" label="字符数" width="90" />
        <!-- 页码来自解析文本里的【第 N 页】标记，问答时用来标注来源位置 -->
        <el-table-column prop="page_no" label="页码" width="80">
          <template #default="scope">{{ scope.row.page_no || '-' }}</template>
        </el-table-column>
        <el-table-column prop="vector_status" label="向量化状态" width="120" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="scope">
            <!-- 打开编辑弹窗，人工修正切歪了的片段 -->
            <el-button type="primary" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <!-- 只把当前行的 id 传给删除方法 -->
            <el-button type="danger" size="small" @click="del(scope.row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <!-- data.total 为 0 时整个分页条不渲染 -->
    <div class="card" v-if="data.total">
      <!-- 切换页码时更新 data.pageNum 并触发 load 重新查询 -->
      <el-pagination
          v-model:current-page="data.pageNum"
          background
          layout="prev, pager, next"
          :page-size="data.pageSize"
          :total="data.total"
          @current-change="load"
      />
    </div>

    <!-- 片段编辑弹窗，只允许改正文 -->
    <el-dialog title="编辑片段" v-model="data.formVisible" width="55%" destroy-on-close>
      <div style="margin-bottom: 8px; color: #999; font-size: 12px">
        修改后这一段需要重新向量化，所属文档的向量化状态会回到待向量化
      </div>
      <!-- 输入值存进 data.form.content，保存时写进 knowledge_chunk.content -->
      <el-input v-model="data.form.content" type="textarea" :rows="12"></el-input>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 控制片段编辑弹窗的显示隐藏
  formVisible: false,
  // 弹窗里绑定的片段对象，只用到 id 和 content 两个字段
  form: {},
  // 表格数据，由 /knowledgeChunk/selectPage 返回的 list 填充
  tableData: [],
  // 知识库下拉选项，来自 /knowledgeBase/selectAll
  kbOptions: [],
  // 文档下拉选项，来自 /knowledgeDocument/selectPage，随知识库切换而变
  docOptions: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部知识库下拉框的值
  kbId: '',
  // 顶部文档下拉框的值
  documentId: '',
  // 顶部片段类型下拉框的值
  chunkType: '',
  // 顶部内容搜索框的值
  keyword: '',
  // 表格勾选中的行 id 集合，批量删除时提交它
  ids: []
})

const loadKbOptions = () => {
  // 只返回正常状态的知识库
  request.get('/knowledgeBase/selectAll').then(res => {
    if (res.code === '200') {
      data.kbOptions = res.data || []
    }
  })
}

const loadDocOptions = () => {
  // 没选知识库时文档下拉框清空，避免列出所有库的文档
  if (!data.kbId) {
    data.docOptions = []
    return
  }
  // page_size 给大一点，一个库下的文档一次取完，下拉框不做分页
  request.get('/knowledgeDocument/selectPage', {
    params: { kb_id: data.kbId, page_num: 1, page_size: 200 }
  }).then(res => {
    if (res.code === '200') {
      data.docOptions = res.data?.list || []
    }
  })
}

const onKbChange = () => {
  // 换了知识库，原来选中的文档已经不属于这个库了，清空重选
  data.documentId = ''
  loadDocOptions()
  load()
}

const load = () => {
  // 分页查询接口，六个参数分别来自页码、每页条数、知识库、文档、片段类型、内容关键字
  request.get('/knowledgeChunk/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      kb_id: data.kbId || undefined,
      document_id: data.documentId || undefined,
      chunk_type: data.chunkType,
      keyword: data.keyword
    }
  }).then(res => {
    if (res.code === '200') {
      // res.data 是后端的 PageInfo，list 渲染表格，total 驱动分页条
      data.tableData = res.data?.list || []
      data.total = res.data?.total || 0
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const handleEdit = (row) => {
  // 只把 id 和正文带进弹窗，其他字段由切分产生，页面不允许改
  data.form = { id: row.id, content: row.content }
  data.formVisible = true
}

const save = () => {
  // 提交修改后的正文，后端会同时把这一段和所属文档的向量化状态改回待向量化
  request.put('/knowledgeChunk/update', data.form).then(res => {
    if (res.code === '200') {
      ElMessage.success('保存成功')
      data.formVisible = false
      load()
    } else {
      // 内容为空这类业务失败，后端在 msg 里返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/knowledgeChunk/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        // 删完重新查列表，文档和知识库上的片段数也已经被后端重算过
        load()
      } else {
        // 父块不允许单独删除，后端会拦下来
        ElMessage.error(res.msg)
      }
    })
  })
}

const delBatch = () => {
  // 一行都没勾就点批量删除，前端直接拦住，不发请求
  if (!data.ids.length) {
    ElMessage.warning('请选择数据')
    return
  }
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    // delete 请求的请求体要写在 config.data 里，后端按 JSON 数组接收
    request.delete('/knowledgeChunk/deleteBatch', { data: data.ids }).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const handleSelectionChange = (rows) => {
  // 表格勾选变化时把选中行的 id 抽出来存进 data.ids，供批量删除使用
  data.ids = rows.map(item => item.id)
}

const chunkTypeColor = (type) => {
  // 父块只做上下文回填用蓝色，子块参与检索用绿色，普通块用默认灰
  if (type === '父块') {
    return 'primary'
  }
  if (type === '子块') {
    return 'success'
  }
  return 'info'
}

const reset = () => {
  // 清空四个搜索条件并回到第一页，再查一次完整列表
  data.kbId = ''
  data.documentId = ''
  data.chunkType = ''
  data.keyword = ''
  data.docOptions = []
  data.pageNum = 1
  load()
}

// 页面加载时先取知识库下拉数据，再查第一页片段
loadKbOptions()
load()
</script>
