<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 输入的名称存进 data.name，点查询时作为 name 参数传给后端做模糊匹配 -->
      <el-input v-model="data.name" style="width: 240px; margin-right: 10px" placeholder="请输入知识库名称查询"></el-input>
      <!-- 选中的状态存进 data.status，作为 status 参数传给后端做精确匹配 -->
      <el-select v-model="data.status" clearable style="width: 180px; margin-right: 10px" placeholder="请选择状态">
        <el-option label="正常" value="正常"></el-option>
        <el-option label="停用" value="停用"></el-option>
      </el-select>
      <!-- 直接调 load，带上当前两个搜索条件重新查询 -->
      <el-button type="info" plain @click="load">查询</el-button>
      <!-- 清空搜索条件并回到第一页 -->
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 打开空白弹窗，走新增流程 -->
      <el-button type="primary" plain @click="handleAdd">新增</el-button>
      <!-- 删除表格里勾选中的多行 -->
      <el-button type="danger" plain @click="delBatch">批量删除</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /knowledgeBase/selectPage 返回的 list；勾选变化时把选中行 id 存进 data.ids -->
      <el-table stripe :data="data.tableData" @selection-change="handleSelectionChange">
        <!-- 多选列，配合批量删除使用 -->
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" label="知识库名称" width="200" />
        <!-- show-overflow-tooltip 让过长的描述省略显示，鼠标悬停看全文 -->
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <!-- document_count 由第 06 章的文档增删维护，这里只读展示 -->
        <el-table-column prop="document_count" label="文档数" width="90" />
        <!-- chunk_count 由第 09 章的片段切分维护，这里只读展示 -->
        <el-table-column prop="chunk_count" label="片段数" width="90" />
        <!-- 正常显示绿标签，停用显示灰标签 -->
        <el-table-column prop="status" label="状态" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.status === '正常' ? 'success' : 'info'">{{ scope.row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="创建时间" width="180" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="scope">
            <!-- 看这个库的向量化进度，判断能不能开始问答 -->
            <el-button type="success" size="small" @click="viewVectorStatus(scope.row)">向量状态</el-button>
            <!-- 把当前行数据带进弹窗，走编辑流程 -->
            <el-button type="primary" circle :icon="Edit" @click="handleEdit(scope.row)"></el-button>
            <!-- 只把当前行的 id 传给删除方法 -->
            <el-button type="danger" circle :icon="Delete" @click="del(scope.row.id)"></el-button>
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

    <!-- 新增和编辑共用这一个弹窗，destroy-on-close 保证每次打开都是全新的表单 -->
    <el-dialog title="知识库信息" v-model="data.formVisible" width="40%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="100px" style="padding: 20px">
        <!-- 输入值存进 data.form.name，保存时后端会按它查重 -->
        <el-form-item label="知识库名称" prop="name">
          <el-input v-model="data.form.name" placeholder="请输入知识库名称"></el-input>
        </el-form-item>
        <!-- 多行文本，说明这个库放什么资料，只做展示不参与检索 -->
        <el-form-item label="描述">
          <el-input v-model="data.form.description" type="textarea" :rows="3" placeholder="请输入知识库描述"></el-input>
        </el-form-item>
        <!-- 停用后这个库不参与问答检索，默认新增为正常 -->
        <el-form-item label="状态">
          <el-radio-group v-model="data.form.status">
            <el-radio value="正常">正常</el-radio>
            <el-radio value="停用">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
      </template>
    </el-dialog>

    <!-- 向量状态弹窗，数据来自 /vectorize/status/{kb_id} -->
    <el-dialog title="向量化状态" v-model="data.vectorVisible" width="40%" destroy-on-close>
      <el-form label-width="140px" style="padding: 10px 20px">
        <el-form-item label="知识库">
          <span>{{ data.vectorStatus.kb_name }}</span>
        </el-form-item>
        <!-- 绑定后不允许直接换模型，要换必须先清空向量 -->
        <el-form-item label="绑定的向量模型">
          <span>{{ data.vectorStatus.embedding_model || '尚未绑定' }}</span>
        </el-form-item>
        <!-- 应该有向量的片段数，父块不计入 -->
        <el-form-item label="待检索片段数">
          <span>{{ data.vectorStatus.searchable_count }}</span>
        </el-form-item>
        <!-- 片段表里标记为已完成的数量 -->
        <el-form-item label="已完成向量化">
          <span>{{ data.vectorStatus.done_count }}</span>
        </el-form-item>
        <!-- 向量库里实际存在的条数，和上面对不上说明两边不同步 -->
        <el-form-item label="向量库实际条数">
          <span>{{ data.vectorStatus.vector_count }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <!-- 清空整库向量并解绑模型，用于更换向量模型 -->
        <el-button type="danger" plain @click="clearKbVectors">清空向量并解绑模型</el-button>
        <el-button @click="data.vectorVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 控制知识库信息弹窗的显示隐藏，新增和编辑复用同一个弹窗
  formVisible: false,
  // 弹窗里各输入框绑定的对象。有 id 表示编辑，没有 id 表示新增
  form: {},
  // 表格数据，由 /knowledgeBase/selectPage 返回的 list 填充
  tableData: [],
  // 当前页码，分页组件切换页码时更新它并重新查询
  pageNum: 1,
  // 每页条数，固定 10 条
  pageSize: 10,
  // 总条数，决定分页条显示几页，为 0 时整个分页条不渲染
  total: 0,
  // 顶部名称搜索框的值，作为查询参数传给后端做模糊匹配
  name: '',
  // 顶部状态下拉框的值，作为查询参数传给后端做精确匹配
  status: '',
  // 表格勾选中的行 id 集合，批量删除时提交它
  ids: [],
  // 控制向量状态弹窗的显示隐藏
  vectorVisible: false,
  // 向量化概况，由 /vectorize/status/{kb_id} 填充
  vectorStatus: {},
  // 弹窗的前端校验规则，名称必填
  rules: {
    name: [
      { required: true, message: '请输入知识库名称', trigger: 'blur' }
    ]
  }
})

// formRef 绑定弹窗里的 el-form，点确定时触发整表校验
const formRef = ref()

const load = () => {
  // 分页查询接口，四个参数分别来自页码、每页条数、名称搜索框、状态下拉框
  request.get('/knowledgeBase/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      name: data.name,
      status: data.status
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

const handleAdd = () => {
  // 新增时给一份干净的默认值，没有 id，save 时会走新增接口；
  // 状态默认正常，和后端 add 的默认值保持一致
  data.form = { status: '正常' }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变；
  // 拷贝过来的对象带 id，save 时会走更新接口
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    // 名称没填时不发请求，输入框下方直接红字提示
    if (!valid) {
      return
    }
    // data.form.id 存在说明当前弹窗是编辑模式，后端按 id 更新 knowledge_base 表原记录
    // data.form.id 不存在说明是新增模式，后端会插入一条新知识库记录
    const action = data.form.id
        ? request.put('/knowledgeBase/update', data.form)
        : request.post('/knowledgeBase/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        // 关掉弹窗并重新查一次列表，让表格显示最新数据
        data.formVisible = false
        load()
      } else {
        // 名称重复、状态参数错误这些业务失败，后端在 msg 里返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    // id 拼在路径上，后端用路径参数接收
    request.delete('/knowledgeBase/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        // 删完重新查列表，被删的行从表格里消失
        load()
      } else {
        // 库下还有文档时后端会拦下来，提示在 msg 里
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
    request.delete('/knowledgeBase/deleteBatch', { data: data.ids }).then(res => {
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

const viewVectorStatus = (row) => {
  // 三个数字放在一起看：应该有多少、标记完成多少、向量库里实际多少
  request.get('/vectorize/status/' + row.id).then(res => {
    if (res.code === '200') {
      data.vectorStatus = res.data
      data.vectorVisible = true
    } else {
      // 向量库连不上时后端会给出明确提示
      ElMessage.error(res.msg)
    }
  })
}

const clearKbVectors = () => {
  // 清空整库向量会解除向量模型绑定，之后可以改用别的模型重做
  ElMessageBox.confirm('清空后整个知识库需要重新向量化，确定继续吗？', '清空确认', { type: 'warning' }).then(() => {
    request.delete('/vectorize/knowledgeBase/' + data.vectorStatus.kb_id).then(res => {
      if (res.code === '200') {
        // res.data 里带着清掉了多少条向量
        ElMessage.success(res.data)
        data.vectorVisible = false
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const reset = () => {
  // 清空两个搜索条件并回到第一页，再查一次完整列表
  data.name = ''
  data.status = ''
  data.pageNum = 1
  load()
}

// 页面加载时立刻查一次，进入页面就能看到第一页数据
load()
</script>
