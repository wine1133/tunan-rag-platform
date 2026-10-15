<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 输入的配置名称存进 data.name，作为 name 参数做模糊匹配 -->
      <el-input v-model="data.name" style="width: 220px; margin-right: 10px" placeholder="请输入配置名称查询"></el-input>
      <!-- 选中的模型类型存进 data.modelType，作为 model_type 参数做精确匹配 -->
      <el-select v-model="data.modelType" clearable style="width: 160px; margin-right: 10px" placeholder="请选择模型类型">
        <el-option label="对话模型" value="对话模型"></el-option>
        <el-option label="向量模型" value="向量模型"></el-option>
        <el-option label="重排模型" value="重排模型"></el-option>
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
      <!-- data.tableData 来自 /aiModelConfig/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData">
        <el-table-column prop="name" label="配置名称" width="180" />
        <!-- 三类模型用不同颜色区分，一眼看出哪类配置齐了 -->
        <el-table-column prop="model_type" label="模型类型" width="110">
          <template #default="scope">
            <el-tag :type="modelTypeColor(scope.row.model_type)" size="small">{{ scope.row.model_type }}</el-tag>
          </template>
        </el-table-column>
        <!-- 协议决定代码走 OpenAI 兼容还是 DashScope 原生那条调用路径 -->
        <el-table-column prop="protocol" label="接口协议" width="130" />
        <el-table-column prop="model_name" label="模型名称" width="170" />
        <el-table-column prop="base_url" label="接口地址" show-overflow-tooltip />
        <!-- 密钥由后端脱敏，只返回头尾各 4 位 -->
        <el-table-column prop="api_key" label="密钥" width="170">
          <template #default="scope">{{ scope.row.api_key || '未填写' }}</template>
        </el-table-column>
        <!-- 向量维度只有向量模型有值，必须和 PGVector 建表维度一致 -->
        <el-table-column prop="dimension" label="维度" width="80">
          <template #default="scope">{{ scope.row.dimension || '-' }}</template>
        </el-table-column>
        <!-- 同一类型下只有一条是启用的，代码只认启用的那条 -->
        <el-table-column prop="enabled" label="启用" width="80">
          <template #default="scope">
            <el-tag :type="scope.row.enabled === '是' ? 'success' : 'info'" size="small">{{ scope.row.enabled }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="scope">
            <!-- 用库里保存的配置真实调一次模型，确认地址、密钥、模型名都对 -->
            <el-button type="success" size="small" :loading="data.testingId === scope.row.id" @click="testConnection(scope.row)">测试</el-button>
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
    <el-dialog title="AI 模型配置" v-model="data.formVisible" width="50%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="110px" style="padding: 20px">
        <el-form-item label="配置名称" prop="name">
          <el-input v-model="data.form.name" placeholder="请输入配置名称"></el-input>
        </el-form-item>
        <!-- 选向量模型后下面会多出向量维度这一项 -->
        <el-form-item label="模型类型" prop="model_type">
          <el-select v-model="data.form.model_type" style="width: 100%" @change="onModelTypeChange">
            <el-option label="对话模型" value="对话模型"></el-option>
            <el-option label="向量模型" value="向量模型"></el-option>
            <el-option label="重排模型" value="重排模型"></el-option>
          </el-select>
        </el-form-item>
        <!-- 对话和向量走 OpenAI 兼容，重排只有 DashScope 原生，切类型时自动带出 -->
        <el-form-item label="接口协议" prop="protocol">
          <el-select v-model="data.form.protocol" style="width: 100%">
            <el-option label="OpenAI兼容" value="OpenAI兼容"></el-option>
            <el-option label="DashScope原生" value="DashScope原生"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="服务商">
          <el-input v-model="data.form.provider" placeholder="例如：阿里云百炼"></el-input>
        </el-form-item>
        <el-form-item label="接口地址" prop="base_url">
          <el-input v-model="data.form.base_url" placeholder="OpenAI兼容填 .../compatible-mode/v1，原生填 .../api/v1"></el-input>
        </el-form-item>
        <!-- 编辑时这里显示的是脱敏串，不重新输入就保持原密钥不变。
             show-password 让密钥始终以圆点显示，粘贴进来的新密钥也不会明文暴露在屏幕上，
             需要核对时点输入框右侧的小眼睛切换成明文 -->
        <el-form-item label="API Key">
          <el-input show-password v-model="data.form.api_key" placeholder="留空表示不修改原密钥"></el-input>
        </el-form-item>
        <el-form-item label="模型名称" prop="model_name">
          <el-input v-model="data.form.model_name" placeholder="例如：qwen-plus、text-embedding-v4、gte-rerank-v2"></el-input>
        </el-form-item>
        <!-- 只有向量模型需要维度，必须和 PGVector 建表时的 vector(N) 一致 -->
        <el-form-item v-if="data.form.model_type === '向量模型'" label="向量维度" prop="dimension">
          <el-input-number v-model="data.form.dimension" :min="64" :max="4096" :step="64" style="width: 100%"></el-input-number>
        </el-form-item>
        <!-- 设为启用后，同类型其他配置会被后端自动停用 -->
        <el-form-item label="启用">
          <el-radio-group v-model="data.form.enabled">
            <el-radio value="是">是</el-radio>
            <el-radio value="否">否</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="data.form.remark" type="textarea" :rows="2" placeholder="说明这条配置用在什么地方"></el-input>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 控制配置弹窗的显示隐藏，新增和编辑复用同一个弹窗
  formVisible: false,
  // 弹窗里各输入框绑定的对象。有 id 表示编辑，没有 id 表示新增
  form: {},
  // 表格数据，由 /aiModelConfig/selectPage 返回的 list 填充
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部配置名称搜索框的值
  name: '',
  // 顶部模型类型下拉框的值
  modelType: '',
  // 正在测试连通性的那一行 id，用来给对应的按钮加转圈效果
  testingId: 0,
  // 弹窗的前端校验规则
  rules: {
    name: [
      { required: true, message: '请输入配置名称', trigger: 'blur' }
    ],
    model_type: [
      { required: true, message: '请选择模型类型', trigger: 'change' }
    ],
    protocol: [
      { required: true, message: '请选择接口协议', trigger: 'change' }
    ],
    base_url: [
      { required: true, message: '请输入接口地址', trigger: 'blur' }
    ],
    model_name: [
      { required: true, message: '请输入模型名称', trigger: 'blur' }
    ]
  }
})

// formRef 绑定弹窗里的 el-form，点确定时触发整表校验
const formRef = ref()

const load = () => {
  // 分页查询接口，四个参数分别来自页码、每页条数、名称搜索框、类型下拉框
  request.get('/aiModelConfig/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      name: data.name,
      model_type: data.modelType
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
  // 新增时默认按对话模型给一份百炼的配置模板，改改模型名就能用
  data.form = {
    model_type: '对话模型',
    protocol: 'OpenAI兼容',
    provider: '阿里云百炼',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    enabled: '否'
  }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变；
  // 密钥字段带过来的是脱敏串，不重新输入的话后端会保留原密钥
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const onModelTypeChange = (type) => {
  // 百炼只有重排接口不在 OpenAI 兼容模式下，切换类型时把协议和地址一起带出来，
  // 省掉管理员自己去查文档
  if (type === '重排模型') {
    data.form.protocol = 'DashScope原生'
    data.form.base_url = 'https://dashscope.aliyuncs.com/api/v1'
  } else {
    data.form.protocol = 'OpenAI兼容'
    data.form.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
  }
}

const save = () => {
  formRef.value.validate(valid => {
    // 必填项没填时不发请求，表单项下方直接红字提示
    if (!valid) {
      return
    }
    // data.form.id 存在说明当前弹窗是编辑模式，后端按 id 更新 ai_model_config 表原记录
    // data.form.id 不存在说明是新增模式，后端会插入一条新配置记录
    const action = data.form.id
        ? request.put('/aiModelConfig/update', data.form)
        : request.post('/aiModelConfig/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        // 关掉弹窗并重新查一次列表，让表格显示最新数据
        data.formVisible = false
        load()
      } else {
        // 名称重复、向量模型没填维度这些业务失败，后端在 msg 里返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const testConnection = (row) => {
  // 记下正在测哪一行，按钮转圈期间不重复点
  data.testingId = row.id
  request.post('/aiModelConfig/test/' + row.id).then(res => {
    if (res.code === '200') {
      // res.data 是后端返回的成功说明，例如"向量模型连通正常，输出 1024 维向量"
      ElMessage.success(res.data)
    } else {
      // 密钥无效、模型名不存在、维度对不上，后端都翻译成了人话
      ElMessage.error(res.msg)
    }
  }).finally(() => {
    data.testingId = 0
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/aiModelConfig/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        // 启用中的配置不允许删除，后端会拦下来
        ElMessage.error(res.msg)
      }
    })
  })
}

const modelTypeColor = (type) => {
  // 对话模型绿色、向量模型蓝色、重排模型橙色
  if (type === '对话模型') {
    return 'success'
  }
  if (type === '向量模型') {
    return 'primary'
  }
  return 'warning'
}

const reset = () => {
  // 清空两个搜索条件并回到第一页，再查一次完整列表
  data.name = ''
  data.modelType = ''
  data.pageNum = 1
  load()
}

// 页面加载时立刻查一次，进入页面就能看到第一页数据
load()
</script>
