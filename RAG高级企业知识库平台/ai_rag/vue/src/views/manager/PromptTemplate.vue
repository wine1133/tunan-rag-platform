<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 输入的模板名称存进 data.keyword，作为 keyword 参数做模糊匹配 -->
      <el-input v-model="data.keyword" style="width: 220px; margin-right: 10px" placeholder="请输入模板名称查询"></el-input>
      <!-- 选中的场景存进 data.scene，作为 scene 参数做精确匹配 -->
      <el-select v-model="data.scene" clearable style="width: 180px; margin-right: 10px" placeholder="请选择使用场景">
        <el-option label="问答生成" value="问答生成"></el-option>
        <el-option label="查询改写" value="查询改写"></el-option>
        <el-option label="Agentic RAG" value="Agentic RAG"></el-option>
        <el-option label="评测集构建" value="评测集构建"></el-option>
      </el-select>
      <!-- 直接调 load，带上当前两个搜索条件重新查询 -->
      <el-button type="info" plain @click="load">查询</el-button>
      <!-- 清空搜索条件并回到第一页 -->
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 打开空白弹窗，走新增流程 -->
      <el-button type="primary" plain @click="handleAdd">新增</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /promptTemplate/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData">
        <!-- 代码里按 code 取模板，全表唯一 -->
        <el-table-column prop="code" label="模板编码" width="200" />
        <el-table-column prop="name" label="模板名称" width="160" />
        <el-table-column prop="scene" label="使用场景" width="130" />
        <!-- variables 由后端从内容里自动抽取，不用手工维护 -->
        <el-table-column prop="variables" label="变量" width="160" show-overflow-tooltip />
        <el-table-column prop="content" label="模板内容" show-overflow-tooltip />
        <!-- 停用的模板取不到，链路会直接报错而不是偷偷用旧内容 -->
        <el-table-column prop="enabled" label="启用" width="80">
          <template #default="scope">
            <el-tag :type="scope.row.enabled === '是' ? 'success' : 'info'" size="small">{{ scope.row.enabled }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="scope">
            <!-- 填入变量值看看真正发给模型的完整文本 -->
            <el-button type="success" size="small" @click="openPreview(scope.row)">预览</el-button>
            <!-- 把当前行数据带进弹窗，走编辑流程 -->
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

    <!-- 新增和编辑共用这一个弹窗，destroy-on-close 保证每次打开都是全新的表单 -->
    <el-dialog title="Prompt 模板" v-model="data.formVisible" width="55%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="100px" style="padding: 20px">
        <!-- 编码是代码取模板的依据，编辑已有模板时改它会让对应功能取不到模板 -->
        <el-form-item label="模板编码" prop="code">
          <el-input v-model="data.form.code" placeholder="例如：RAG_ANSWER"></el-input>
        </el-form-item>
        <el-form-item label="模板名称" prop="name">
          <el-input v-model="data.form.name" placeholder="请输入模板名称"></el-input>
        </el-form-item>
        <el-form-item label="使用场景">
          <el-select v-model="data.form.scene" clearable style="width: 100%" placeholder="请选择使用场景">
            <el-option label="问答生成" value="问答生成"></el-option>
            <el-option label="查询改写" value="查询改写"></el-option>
            <el-option label="Agentic RAG" value="Agentic RAG"></el-option>
            <el-option label="评测集构建" value="评测集构建"></el-option>
          </el-select>
        </el-form-item>
        <!-- 用大括号写占位变量，保存时后端会自动抽出变量清单 -->
        <el-form-item label="模板内容" prop="content">
          <el-input v-model="data.form.content" type="textarea" :rows="10" placeholder="用大括号写变量，例如：资料：{context}"></el-input>
        </el-form-item>
        <el-form-item label="启用">
          <el-radio-group v-model="data.form.enabled">
            <el-radio value="是">是</el-radio>
            <el-radio value="否">否</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="data.form.remark" type="textarea" :rows="2" placeholder="说明这个模板用在哪个环节"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
      </template>
    </el-dialog>

    <!-- 预览弹窗：为模板里的每个变量填一个值，看看渲染后的完整文本 -->
    <el-dialog title="预览 Prompt" v-model="data.previewVisible" width="55%" destroy-on-close>
      <el-form label-width="100px" style="padding: 0 20px">
        <!-- 变量清单来自模板的 variables 列，逐个生成一个输入框 -->
        <el-form-item v-for="name in data.previewNames" :key="name" :label="name">
          <el-input v-model="data.previewValues[name]" :placeholder="'请输入 ' + name + ' 的值'"></el-input>
        </el-form-item>
      </el-form>
      <el-button type="primary" style="margin: 0 20px 10px" @click="doPreview">生成预览</el-button>
      <!-- white-space 保留模板里的换行，看到的排版就是发给模型的排版 -->
      <div v-if="data.previewText" style="margin: 0 20px; max-height: 360px; overflow: auto; background: #f7f7f7; padding: 12px; white-space: pre-wrap; font-size: 13px">{{ data.previewText }}</div>
      <template #footer>
        <el-button @click="data.previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 控制模板弹窗的显示隐藏，新增和编辑复用同一个弹窗
  formVisible: false,
  // 弹窗里各输入框绑定的对象。有 id 表示编辑，没有 id 表示新增
  form: {},
  // 表格数据，由 /promptTemplate/selectPage 返回的 list 填充
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部模板名称搜索框的值
  keyword: '',
  // 顶部使用场景下拉框的值
  scene: '',
  // 控制预览弹窗的显示隐藏
  previewVisible: false,
  // 当前预览的模板 id
  previewId: 0,
  // 当前模板需要的变量名列表，来自 variables 列
  previewNames: [],
  // 各变量填入的值，键是变量名
  previewValues: {},
  // 渲染后的完整文本
  previewText: '',
  // 弹窗的前端校验规则
  rules: {
    code: [
      { required: true, message: '请输入模板编码', trigger: 'blur' }
    ],
    name: [
      { required: true, message: '请输入模板名称', trigger: 'blur' }
    ],
    content: [
      { required: true, message: '请输入模板内容', trigger: 'blur' }
    ]
  }
})

// formRef 绑定弹窗里的 el-form，点确定时触发整表校验
const formRef = ref()

const load = () => {
  // 分页查询接口，四个参数分别来自页码、每页条数、名称搜索框、场景下拉框
  request.get('/promptTemplate/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      keyword: data.keyword,
      scene: data.scene
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
  // 新增时默认启用，没有 id，save 时会走新增接口
  data.form = { enabled: '是' }
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
    // 必填项没填时不发请求，表单项下方直接红字提示
    if (!valid) {
      return
    }
    // data.form.id 存在说明当前弹窗是编辑模式，后端按 id 更新 prompt_template 表原记录
    // data.form.id 不存在说明是新增模式，后端会插入一条新模板记录
    const action = data.form.id
        ? request.put('/promptTemplate/update', data.form)
        : request.post('/promptTemplate/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        // 关掉弹窗并重新查一次列表，变量列会显示后端刚抽出来的变量清单
        data.formVisible = false
        load()
      } else {
        // 编码重复、内容为空这些业务失败，后端在 msg 里返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const openPreview = (row) => {
  // 变量清单存在 variables 列里，逗号分隔，拆开后给每个变量生成一个输入框
  data.previewId = row.id
  data.previewNames = row.variables ? row.variables.split(',').filter(item => item) : []
  data.previewValues = {}
  data.previewText = ''
  data.previewVisible = true
}

const doPreview = () => {
  // 后端按模板编码取内容，把变量值替换进去，返回真正会发给模型的文本
  request.post('/promptTemplate/preview', { id: data.previewId, values: data.previewValues }).then(res => {
    if (res.code === '200') {
      data.previewText = res.data
    } else {
      // 变量没填全时后端会明确指出缺哪些
      ElMessage.error(res.msg)
    }
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/promptTemplate/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const reset = () => {
  // 清空两个搜索条件并回到第一页，再查一次完整列表
  data.keyword = ''
  data.scene = ''
  data.pageNum = 1
  load()
}

// 页面加载时立刻查一次，进入页面就能看到第一页数据
load()
</script>
