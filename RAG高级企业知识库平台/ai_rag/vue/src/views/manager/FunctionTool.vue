<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 输入的工具名称存进 data.keyword，作为 keyword 参数做模糊匹配 -->
      <el-input v-model="data.keyword" style="width: 220px; margin-right: 10px" placeholder="请输入工具名称查询"></el-input>
      <el-select v-model="data.enabled" clearable style="width: 140px; margin-right: 10px" placeholder="启用状态">
        <el-option label="启用" value="是"></el-option>
        <el-option label="停用" value="否"></el-option>
      </el-select>
      <el-button type="info" plain @click="load">查询</el-button>
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>
    <div class="card" style="margin-bottom: 5px">
      <el-button type="primary" plain @click="handleAdd">新增</el-button>
      <!-- 看真正会发给模型的工具定义，改完描述立刻能验证 -->
      <el-button type="success" plain @click="viewDefinitions">查看模型收到的工具定义</el-button>
      <!-- 按工具统计调用次数和成功率 -->
      <el-button type="warning" plain @click="viewSummary">调用统计</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /functionTool/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData">
        <el-table-column prop="tool_code" label="工具编码" width="180" />
        <el-table-column prop="tool_name" label="工具名称" width="150" />
        <!-- 这段描述会原样发给模型，模型靠它判断什么时候该调这个工具 -->
        <el-table-column prop="description" label="工具描述（会发给模型）" show-overflow-tooltip />
        <!-- 表里配了但代码里没实现的工具，模型拿不到，这里标出来 -->
        <el-table-column prop="implemented" label="代码实现" width="100">
          <template #default="scope">
            <el-tag :type="scope.row.implemented ? 'success' : 'danger'" size="small">
              {{ scope.row.implemented ? '已实现' : '未实现' }}
            </el-tag>
          </template>
        </el-table-column>
        <!-- 真开关：关掉之后模型下一次执行就拿不到这个工具 -->
        <el-table-column prop="enabled" label="启用" width="100">
          <template #default="scope">
            <el-switch
                :model-value="scope.row.enabled === '是'"
                @change="toggle(scope.row, $event)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="sort" label="排序" width="80" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="scope">
            <el-button type="primary" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button type="danger" size="small" @click="del(scope.row.id)">删除</el-button>
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

    <!-- 新增和编辑共用这一个弹窗 -->
    <el-dialog title="Function 工具" v-model="data.formVisible" width="50%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="110px" style="padding: 20px">
        <!-- 编码必须和 ai/tools.py 里实现函数的名字一致 -->
        <el-form-item label="工具编码" prop="tool_code">
          <el-input v-model="data.form.tool_code" placeholder="必须和 ai/tools.py 里的函数名一致"></el-input>
        </el-form-item>
        <el-form-item label="工具名称" prop="tool_name">
          <el-input v-model="data.form.tool_name" placeholder="给人看的名称"></el-input>
        </el-form-item>
        <!-- 这段文字会原样发给模型，写得越准模型调用得越准 -->
        <el-form-item label="工具描述" prop="description">
          <el-input v-model="data.form.description" type="textarea" :rows="3" placeholder="写清楚这个工具能做什么、什么时候该用它，这段会原样发给模型"></el-input>
        </el-form-item>
        <!-- 入参说明 JSON，键是参数名，值是这个参数的含义 -->
        <el-form-item label="入参说明">
          <el-input v-model="data.form.input_schema" type="textarea" :rows="3" placeholder='例如：{"query":"检索问题","kb_id":"知识库ID"}'></el-input>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="data.form.sort" :min="0" :max="999" style="width: 100%"></el-input-number>
        </el-form-item>
        <el-form-item label="启用">
          <el-radio-group v-model="data.form.enabled">
            <el-radio value="是">是</el-radio>
            <el-radio value="否">否</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
      </template>
    </el-dialog>

    <!-- 工具定义预览：这就是模型真正会收到的内容 -->
    <el-dialog title="模型收到的工具定义" v-model="data.definitionVisible" width="60%" destroy-on-close>
      <div style="max-height: 460px; overflow: auto; background: #f7f7f7; padding: 12px; white-space: pre-wrap; font-size: 13px">{{ data.definitionText }}</div>
      <template #footer>
        <el-button @click="data.definitionVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 调用统计：每个工具被调了多少次、失败多少次 -->
    <el-dialog title="工具调用统计" v-model="data.summaryVisible" width="55%" destroy-on-close>
      <el-table stripe :data="data.summary" size="small">
        <el-table-column prop="tool_name" label="工具" width="160" />
        <el-table-column prop="enabled" label="启用" width="80" />
        <el-table-column prop="total" label="调用次数" width="110" />
        <el-table-column prop="failed" label="失败次数" width="110" />
        <el-table-column prop="success_rate" label="成功率（%）">
          <template #default="scope">{{ scope.row.success_rate ?? '—' }}</template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="data.summaryVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  formVisible: false,
  form: {},
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部工具名称搜索框的值
  keyword: '',
  // 顶部启用状态下拉框的值
  enabled: '',
  // 控制工具定义预览弹窗
  definitionVisible: false,
  definitionText: '',
  // 控制调用统计弹窗
  summaryVisible: false,
  summary: [],
  rules: {
    tool_code: [
      { required: true, message: '请输入工具编码', trigger: 'blur' }
    ],
    tool_name: [
      { required: true, message: '请输入工具名称', trigger: 'blur' }
    ],
    description: [
      { required: true, message: '请输入工具描述', trigger: 'blur' }
    ]
  }
})

const formRef = ref()

const load = () => {
  request.get('/functionTool/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      keyword: data.keyword,
      enabled: data.enabled
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

const handleAdd = () => {
  // 新增时默认启用、排序放最后
  data.form = { enabled: '是', sort: 0 }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const action = data.form.id
        ? request.put('/functionTool/update', data.form)
        : request.post('/functionTool/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        data.formVisible = false
        load()
      } else {
        // 编码重复、描述为空这些业务失败，后端在 msg 里返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const toggle = (row, checked) => {
  // 开关一改，模型下一次执行拿到的工具清单就变了，不用重启服务
  request.put('/functionTool/toggle/' + row.id, null, {
    params: { enabled: checked ? '是' : '否' }
  }).then(res => {
    if (res.code === '200') {
      ElMessage.success(checked ? '已启用' : '已停用')
      load()
    } else {
      ElMessage.error(res.msg)
      load()
    }
  })
}

const del = (id) => {
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/functionTool/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        // 代码里有实现的工具不允许删除，后端会拦下来
        ElMessage.error(res.msg)
      }
    })
  })
}

const viewDefinitions = () => {
  // 展示的是真正发给模型的那段 JSON，改完描述能立刻验证
  request.get('/functionTool/definitions').then(res => {
    if (res.code === '200') {
      data.definitionText = JSON.stringify(res.data, null, 2)
      data.definitionVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const viewSummary = () => {
  request.get('/functionTool/logSummary').then(res => {
    if (res.code === '200') {
      data.summary = res.data || []
      data.summaryVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const reset = () => {
  data.keyword = ''
  data.enabled = ''
  data.pageNum = 1
  load()
}

// 页面加载时立刻查一次
load()
</script>
