<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <el-input v-model="data.name" style="width: 220px; margin-right: 10px" placeholder="请输入应用名称查询"></el-input>
      <el-select v-model="data.status" clearable style="width: 140px; margin-right: 10px" placeholder="状态">
        <el-option label="正常" value="正常"></el-option>
        <el-option label="停用" value="停用"></el-option>
      </el-select>
      <el-button type="info" plain @click="load">查询</el-button>
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>
    <div class="card" style="margin-bottom: 5px">
      <el-button type="primary" plain @click="handleAdd">新增</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /qaApp/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData">
        <el-table-column prop="name" label="应用名称" width="180" />
        <!-- 挂了哪几个库，名称由后端按关联表查出来拼进来 -->
        <el-table-column label="挂载知识库" min-width="200">
          <template #default="scope">
            <el-tag v-for="name in scope.row.kb_names" :key="name" size="small" style="margin-right: 4px">{{ name }}</el-tag>
          </template>
        </el-table-column>
        <!-- 关掉走直线链路，打开走 LangGraph 状态图 -->
        <el-table-column prop="agent_enabled" label="模式" width="130">
          <template #default="scope">
            <el-tag :type="scope.row.agent_enabled === '是' ? 'warning' : 'info'" size="small">
              {{ scope.row.agent_enabled === '是' ? 'Agentic' : '直线链路' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="max_history" label="历史条数" width="100" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="scope">
            <el-tag :type="scope.row.status === '正常' ? 'success' : 'info'" size="small">{{ scope.row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="scope">
            <!-- 直接在管理端试这个应用，不用切到用户端 -->
            <el-button type="success" size="small" @click="openChat(scope.row)">试一下</el-button>
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
    <el-dialog title="问答应用" v-model="data.formVisible" width="55%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="120px" style="padding: 10px 20px">
        <el-form-item label="应用名称" prop="name">
          <el-input v-model="data.form.name" placeholder="请输入应用名称"></el-input>
        </el-form-item>
        <el-form-item label="应用说明">
          <el-input v-model="data.form.description" type="textarea" :rows="2" placeholder="这个应用回答什么范围的问题"></el-input>
        </el-form-item>
        <!-- 一个应用可以挂多个库，检索时在这些库里一起找 -->
        <el-form-item label="挂载知识库" prop="kb_ids">
          <el-select v-model="data.form.kb_ids" multiple style="width: 100%" placeholder="至少选择一个知识库">
            <el-option v-for="kb in data.kbOptions" :key="kb.id" :label="kb.name" :value="kb.id"></el-option>
          </el-select>
        </el-form-item>
        <!-- 不选时用默认检索策略 -->
        <el-form-item label="检索策略">
          <el-select v-model="data.form.retrieval_strategy_id" clearable style="width: 100%" placeholder="不选则使用默认策略">
            <el-option v-for="item in data.strategyOptions" :key="item.id" :label="item.name" :value="item.id"></el-option>
          </el-select>
        </el-form-item>
        <!-- 关掉走第 15-19 章的直线链路，打开走第 22 章的状态图 -->
        <el-form-item label="Agentic 模式">
          <el-radio-group v-model="data.form.agent_enabled">
            <el-radio value="否">直线链路</el-radio>
            <el-radio value="是">Agentic（模型自行判断是否重查）</el-radio>
          </el-radio-group>
        </el-form-item>
        <!-- 带进模型的历史消息条数，0 表示不带历史 -->
        <el-form-item label="历史消息条数">
          <el-input-number v-model="data.form.max_history" :min="0" :max="20" style="width: 100%"></el-input-number>
        </el-form-item>
        <!-- 检索不到资料时说这句话，不让模型硬编 -->
        <el-form-item label="兜底话术">
          <el-input v-model="data.form.empty_answer" placeholder="检索不到资料时回复的内容"></el-input>
        </el-form-item>
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
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'
import router from '@/router/index.js'

const data = reactive({
  formVisible: false,
  form: {},
  tableData: [],
  // 知识库和检索策略两份下拉数据
  kbOptions: [],
  strategyOptions: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  name: '',
  status: '',
  rules: {
    name: [
      { required: true, message: '请输入应用名称', trigger: 'blur' }
    ],
    kb_ids: [
      { required: true, message: '请至少选择一个知识库', trigger: 'change' }
    ]
  }
})

const formRef = ref()

const loadOptions = () => {
  request.get('/knowledgeBase/selectAll').then(res => {
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

const load = () => {
  request.get('/qaApp/selectPage', {
    params: { page_num: data.pageNum, page_size: data.pageSize, name: data.name, status: data.status }
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
  // 新增时默认走直线链路，历史带 6 条，兜底话术给一句标准的
  data.form = {
    kb_ids: [],
    agent_enabled: '否',
    max_history: 6,
    empty_answer: '知识库中未找到相关内容。',
    status: '正常'
  }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，kb_ids 由后端按关联表查出来一并返回
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const save = () => {
  formRef.value.validate(valid => {
    if (!valid) {
      return
    }
    const action = data.form.id
        ? request.put('/qaApp/update', data.form)
        : request.post('/qaApp/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        data.formVisible = false
        load()
      } else {
        // 名称重复、没挂知识库、历史条数越界，后端都返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const del = (id) => {
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/qaApp/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        load()
      } else {
        ElMessage.error(res.msg)
      }
    })
  })
}

const openChat = (row) => {
  // 带着应用ID跳到问答页面，直接对着这个应用提问
  router.push('/manager/qaChat?appId=' + row.id)
}

const reset = () => {
  data.name = ''
  data.status = ''
  data.pageNum = 1
  load()
}

loadOptions()
load()
</script>
