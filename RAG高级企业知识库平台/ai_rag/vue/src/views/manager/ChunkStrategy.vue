<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 输入的策略名称存进 data.name，作为 name 参数做模糊匹配 -->
      <el-input v-model="data.name" style="width: 220px; margin-right: 10px" placeholder="请输入策略名称查询"></el-input>
      <!-- 选中的类型存进 data.strategyType，作为 strategy_type 参数做精确匹配 -->
      <el-select v-model="data.strategyType" clearable style="width: 180px; margin-right: 10px" placeholder="请选择策略类型">
        <el-option label="递归分块" value="递归分块"></el-option>
        <el-option label="父子分块" value="父子分块"></el-option>
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
      <!-- data.tableData 来自 /chunkStrategy/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData">
        <el-table-column prop="name" label="策略名称" width="200" />
        <el-table-column prop="strategy_type" label="策略类型" width="120" />
        <!-- 递归分块只切一层，父子分块要先切父块再切子块 -->
        <el-table-column prop="chunk_size" label="片段长度" width="100" />
        <el-table-column prop="chunk_overlap" label="重叠字符" width="100" />
        <!-- 父块长度只有父子分块用得上，递归分块这一列是空的 -->
        <el-table-column prop="parent_chunk_size" label="父块长度" width="100">
          <template #default="scope">{{ scope.row.parent_chunk_size || '-' }}</template>
        </el-table-column>
        <el-table-column prop="separators" label="分隔符" width="160" show-overflow-tooltip />
        <!-- 全表只有一条是默认策略，知识库没单独配策略时用它 -->
        <el-table-column prop="is_default" label="默认" width="80">
          <template #default="scope">
            <el-tag v-if="scope.row.is_default === '是'" type="success" size="small">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" show-overflow-tooltip />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="scope">
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
    <el-dialog title="切分策略" v-model="data.formVisible" width="45%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="110px" style="padding: 20px">
        <el-form-item label="策略名称" prop="name">
          <el-input v-model="data.form.name" placeholder="请输入策略名称"></el-input>
        </el-form-item>
        <!-- 选择父子分块后下面会多出父块长度这一项 -->
        <el-form-item label="策略类型" prop="strategy_type">
          <el-select v-model="data.form.strategy_type" style="width: 100%">
            <el-option label="递归分块" value="递归分块"></el-option>
            <el-option label="父子分块" value="父子分块"></el-option>
          </el-select>
        </el-form-item>
        <!-- 片段长度是切分的目标字符数，父子分块时它是子块的长度 -->
        <el-form-item label="片段长度" prop="chunk_size">
          <el-input-number v-model="data.form.chunk_size" :min="50" :max="4000" :step="50" style="width: 100%"></el-input-number>
        </el-form-item>
        <!-- 相邻片段重叠一部分，防止一句话正好被切断后两边都读不通 -->
        <el-form-item label="重叠字符" prop="chunk_overlap">
          <el-input-number v-model="data.form.chunk_overlap" :min="0" :max="1000" :step="10" style="width: 100%"></el-input-number>
        </el-form-item>
        <!-- 只有父子分块需要填父块长度，递归分块时这一项不显示 -->
        <el-form-item v-if="data.form.strategy_type === '父子分块'" label="父块长度" prop="parent_chunk_size">
          <el-input-number v-model="data.form.parent_chunk_size" :min="100" :max="8000" :step="100" style="width: 100%"></el-input-number>
        </el-form-item>
        <!-- 逗号分隔，按顺序逐级尝试；\n 表示换行符，留空时用中文文档的默认分隔符 -->
        <el-form-item label="分隔符">
          <el-input v-model="data.form.separators" placeholder="留空使用默认，例如：\n\n,\n,。,！,？"></el-input>
        </el-form-item>
        <!-- 设为默认后，其他策略的默认标记会被后端自动清掉 -->
        <el-form-item label="设为默认">
          <el-radio-group v-model="data.form.is_default">
            <el-radio value="是">是</el-radio>
            <el-radio value="否">否</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="data.form.remark" type="textarea" :rows="2" placeholder="说明这套参数适合什么资料"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
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
  // 控制策略弹窗的显示隐藏，新增和编辑复用同一个弹窗
  formVisible: false,
  // 弹窗里各输入框绑定的对象。有 id 表示编辑，没有 id 表示新增
  form: {},
  // 表格数据，由 /chunkStrategy/selectPage 返回的 list 填充
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部策略名称搜索框的值
  name: '',
  // 顶部策略类型下拉框的值
  strategyType: '',
  // 弹窗的前端校验规则，名称、类型、长度都必填
  rules: {
    name: [
      { required: true, message: '请输入策略名称', trigger: 'blur' }
    ],
    strategy_type: [
      { required: true, message: '请选择策略类型', trigger: 'change' }
    ],
    chunk_size: [
      { required: true, message: '请填写片段长度', trigger: 'blur' }
    ]
  }
})

// formRef 绑定弹窗里的 el-form，点确定时触发整表校验
const formRef = ref()

const load = () => {
  // 分页查询接口，四个参数分别来自页码、每页条数、名称搜索框、类型下拉框
  request.get('/chunkStrategy/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      name: data.name,
      strategy_type: data.strategyType
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
  // 新增时给一份常用默认值，没有 id，save 时会走新增接口
  data.form = { strategy_type: '递归分块', chunk_size: 500, chunk_overlap: 50, is_default: '否' }
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
    // data.form.id 存在说明当前弹窗是编辑模式，后端按 id 更新 chunk_strategy 表原记录
    // data.form.id 不存在说明是新增模式，后端会插入一条新策略记录
    const action = data.form.id
        ? request.put('/chunkStrategy/update', data.form)
        : request.post('/chunkStrategy/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        // 关掉弹窗并重新查一次列表，让表格显示最新数据
        data.formVisible = false
        load()
      } else {
        // 名称重复、重叠大于片段长度、父块小于子块这些业务失败，后端在 msg 里返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/chunkStrategy/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        // 默认策略不允许删除，后端会拦下来
        ElMessage.error(res.msg)
      }
    })
  })
}

const reset = () => {
  // 清空两个搜索条件并回到第一页，再查一次完整列表
  data.name = ''
  data.strategyType = ''
  data.pageNum = 1
  load()
}

// 页面加载时立刻查一次，进入页面就能看到第一页数据
load()
</script>
