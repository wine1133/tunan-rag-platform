<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 输入的策略名称存进 data.name，作为 name 参数做模糊匹配 -->
      <el-input v-model="data.name" style="width: 240px; margin-right: 10px" placeholder="请输入策略名称查询"></el-input>
      <el-button type="info" plain @click="load">查询</el-button>
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 打开空白弹窗，走新增流程 -->
      <el-button type="primary" plain @click="handleAdd">新增</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /retrievalStrategy/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData">
        <el-table-column prop="name" label="策略名称" width="220" />
        <!-- 把七个开关拼成一串标签，一眼看出这套策略开了哪几步 -->
        <el-table-column label="启用的能力" min-width="320">
          <template #default="scope">
            <el-tag v-if="scope.row.vector_enabled === '是'" size="small" style="margin-right: 4px">向量 {{ scope.row.vector_top_k }}</el-tag>
            <el-tag v-if="scope.row.bm25_enabled === '是'" type="success" size="small" style="margin-right: 4px">BM25 {{ scope.row.bm25_top_k }}</el-tag>
            <el-tag v-if="scope.row.rerank_enabled === '是'" type="warning" size="small" style="margin-right: 4px">重排 {{ scope.row.rerank_top_n }}</el-tag>
            <el-tag v-if="scope.row.query_rewrite_enabled === '是'" type="danger" size="small" style="margin-right: 4px">{{ scope.row.rewrite_type }}</el-tag>
            <el-tag v-if="scope.row.parent_recall_enabled === '是'" type="info" size="small" style="margin-right: 4px">父块回填</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rrf_k" label="RRF k" width="90" />
        <!-- 两个阈值分属两种分数量纲，生效的那个才标绿，一眼看出这套策略实际卡的是哪个 -->
        <el-table-column label="阈值" width="200">
          <template #default="scope">
            <el-tag :type="scope.row.score_scale === '余弦相似度' ? 'success' : 'info'" size="small" style="margin-right: 4px">
              余弦 {{ scope.row.vector_score_threshold ?? '-' }}
            </el-tag>
            <el-tag :type="scope.row.score_scale === '重排相关分' ? 'success' : 'info'" size="small">
              重排 {{ scope.row.rerank_score_threshold ?? '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <!-- 问答应用没配策略时用默认策略，全表只有一条 -->
        <el-table-column prop="is_default" label="默认" width="80">
          <template #default="scope">
            <el-tag v-if="scope.row.is_default === '是'" type="success" size="small">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" show-overflow-tooltip />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="scope">
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
    <el-dialog title="检索策略" v-model="data.formVisible" width="55%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="130px" style="padding: 10px 20px">
        <el-form-item label="策略名称" prop="name">
          <el-input v-model="data.form.name" placeholder="请输入策略名称"></el-input>
        </el-form-item>

        <el-divider content-position="left">一、召回</el-divider>
        <!-- 向量检索懂语义，认不出精确字符 -->
        <el-form-item label="向量检索">
          <el-radio-group v-model="data.form.vector_enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">关闭</el-radio>
          </el-radio-group>
          <el-input-number v-if="data.form.vector_enabled === '是'" v-model="data.form.vector_top_k" :min="1" :max="50" style="margin-left: 20px; width: 130px"></el-input-number>
        </el-form-item>
        <!-- BM25 认字符，听不懂同义表达，两者互补 -->
        <el-form-item label="BM25 检索">
          <el-radio-group v-model="data.form.bm25_enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">关闭</el-radio>
          </el-radio-group>
          <el-input-number v-if="data.form.bm25_enabled === '是'" v-model="data.form.bm25_top_k" :min="1" :max="50" style="margin-left: 20px; width: 130px"></el-input-number>
        </el-form-item>
        <!-- 只有两路都开时才会发生融合，k 越大越偏向被多路同时召回的结果 -->
        <el-form-item v-if="data.form.vector_enabled === '是' && data.form.bm25_enabled === '是'" label="RRF 融合常数">
          <el-input-number v-model="data.form.rrf_k" :min="1" :max="200" style="width: 100%"></el-input-number>
        </el-form-item>

        <el-divider content-position="left">二、精排</el-divider>
        <!-- 重排是交叉编码，比向量相似度准，但每次都要调一次模型 -->
        <el-form-item label="重排">
          <el-radio-group v-model="data.form.rerank_enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">关闭</el-radio>
          </el-radio-group>
          <el-input-number v-if="data.form.rerank_enabled === '是'" v-model="data.form.rerank_top_n" :min="1" :max="20" style="margin-left: 20px; width: 130px"></el-input-number>
        </el-form-item>

        <el-divider content-position="left">三、查询改写</el-divider>
        <!-- 三种改写方式是单选，产出形态不同，串起来会让检索次数继续翻倍 -->
        <el-form-item label="查询改写">
          <el-radio-group v-model="data.form.query_rewrite_enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">关闭</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="data.form.query_rewrite_enabled === '是'" label="改写方式">
          <el-select v-model="data.form.rewrite_type" style="width: 100%">
            <el-option label="多查询扩展" value="多查询扩展"></el-option>
            <el-option label="指代消解" value="指代消解"></el-option>
            <el-option label="HyDE" value="HyDE"></el-option>
          </el-select>
        </el-form-item>
        <!-- 只有多查询扩展用得上条数，其余两种产出一条改写 -->
        <el-form-item v-if="data.form.query_rewrite_enabled === '是' && data.form.rewrite_type === '多查询扩展'" label="扩展条数">
          <el-input-number v-model="data.form.multi_query_count" :min="1" :max="5" style="width: 100%"></el-input-number>
        </el-form-item>

        <el-divider content-position="left">四、后处理</el-divider>
        <!-- 父子分块的库开这个才有意义，普通块的库开了也不生效 -->
        <el-form-item label="父块回填">
          <el-radio-group v-model="data.form.parent_recall_enabled">
            <el-radio value="是">启用</el-radio>
            <el-radio value="否">关闭</el-radio>
          </el-radio-group>
        </el-form-item>
        <!-- 阈值卡的是最终分数，而最终分数是什么量纲由上面几个开关决定，
             所以先把当前组合会走到哪个量纲算出来告诉用户，再让他填对应的那个阈值 -->
        <el-form-item label="当前量纲">
          <el-tag type="success" size="small">{{ data.formScale || '计算中' }}</el-tag>
          <span style="margin-left: 8px; color: #999; font-size: 12px">
            由上面的开关组合决定，下面只有这一档的阈值会生效
          </span>
        </el-form-item>
        <!-- 只在向量单路召回时生效。低于门槛的结果丢掉，问答会走兜底话术 -->
        <el-form-item label="余弦相似度阈值">
          <el-input-number v-model="data.form.vector_score_threshold" :min="0" :max="1" :step="0.05" :precision="3" style="width: 100%"></el-input-number>
          <div :style="{ fontSize: '12px', color: data.formScale === '余弦相似度' ? '#67c23a' : '#999' }">
            向量单路召回时生效。相关片段实测 0.46~0.77，完全无关的问题 0.14~0.23，建议 0.3
          </div>
        </el-form-item>
        <!-- 只在开了重排时生效。重排分和余弦相似度都是 0 到 1，但取值范围差一个数量级 -->
        <el-form-item label="重排相关分阈值">
          <el-input-number v-model="data.form.rerank_score_threshold" :min="0" :max="1" :step="0.01" :precision="3" style="width: 100%"></el-input-number>
          <div :style="{ fontSize: '12px', color: data.formScale === '重排相关分' ? '#67c23a' : '#999' }">
            开了重排时生效。相关片段实测 0.14~0.20，完全无关的问题 0.006，建议 0.05
          </div>
        </el-form-item>
        <!-- 多路召回融合后分数变成名次倒数，没有绝对含义，这时两个阈值都不生效 -->
        <el-form-item v-if="data.formScale === 'RRF名次分'" label=" ">
          <span style="color: #e6a23c; font-size: 12px">
            当前组合的最终分数是 RRF 名次分，它只表示排序先后，不能和固定门槛比大小，本策略不会做阈值过滤。
            要让阈值生效，请打开重排。
          </span>
        </el-form-item>
        <el-form-item label="设为默认">
          <el-radio-group v-model="data.form.is_default">
            <el-radio value="是">是</el-radio>
            <el-radio value="否">否</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="data.form.remark" type="textarea" :rows="2" placeholder="说明这套策略适合什么场景"></el-input>
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
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

const data = reactive({
  // 控制策略弹窗的显示隐藏，新增和编辑复用同一个弹窗
  formVisible: false,
  // 弹窗里各输入框绑定的对象。有 id 表示编辑，没有 id 表示新增
  form: {},
  // 当前表单这套开关组合下，最终分数的量纲，由后端接口算出来。
  // 决定下面两个阈值框哪个会生效
  formScale: '',
  // 表格数据，由 /retrievalStrategy/selectPage 返回的 list 填充
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部策略名称搜索框的值
  name: '',
  // 弹窗的前端校验规则，名称必填
  rules: {
    name: [
      { required: true, message: '请输入策略名称', trigger: 'blur' }
    ]
  }
})

// formRef 绑定弹窗里的 el-form，点确定时触发整表校验
const formRef = ref()

const load = () => {
  // 分页查询接口，三个参数分别来自页码、每页条数、名称搜索框
  request.get('/retrievalStrategy/selectPage', {
    params: { page_num: data.pageNum, page_size: data.pageSize, name: data.name }
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

// 弹窗里拨开关时，重新问后端这套组合的最终分数是什么量纲。
// 推算规则和检索管线是同一套，只在后端 retrieval_service.predict_score_scale 里写一份，
// 前端不自己算，避免两边各写一遍以后改管线时飘掉
const loadFormScale = () => {
  request.post('/retrievalStrategy/scoreScale', data.form).then(res => {
    if (res.code === '200') {
      // 量纲决定下面两个阈值框哪个生效，存进 formScale 供模板判断
      data.formScale = res.data
    }
  })
}

// 影响量纲的就是这几个开关，任意一个变了就重新取一次
watch(
    () => [
      data.form.vector_enabled,
      data.form.bm25_enabled,
      data.form.rerank_enabled,
      data.form.query_rewrite_enabled,
      data.form.rewrite_type,
      data.form.multi_query_count
    ],
    () => {
      // 弹窗没开时不用问
      if (data.formVisible) loadFormScale()
    }
)

const handleAdd = () => {
  // 新增时给一份基线配置：只开向量检索，等价于第 13 章说的基础 RAG
  data.form = {
    vector_enabled: '是',
    vector_top_k: 5,
    bm25_enabled: '否',
    bm25_top_k: 5,
    rrf_k: 60,
    rerank_enabled: '否',
    rerank_top_n: 3,
    query_rewrite_enabled: '否',
    multi_query_count: 3,
    parent_recall_enabled: '否',
    // 两个阈值的默认值按各自量纲的实测区间给：
    // 余弦相似度下相关片段 0.46~0.77、无关 0.14~0.23，0.3 卡在中间
    vector_score_threshold: 0.3,
    // 重排相关分下相关片段 0.14~0.20、无关 0.006，0.05 卡在中间
    rerank_score_threshold: 0.05,
    is_default: '否'
  }
  data.formVisible = true
  // 弹窗打开时先取一次量纲，之后靠 watch 跟着开关变
  loadFormScale()
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变；
  // 拷贝过来的对象带 id，save 时会走更新接口
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
  loadFormScale()
}

const save = () => {
  formRef.value.validate(valid => {
    // 名称没填时不发请求，输入框下方直接红字提示
    if (!valid) {
      return
    }
    // data.form.id 存在说明当前弹窗是编辑模式，后端按 id 更新 retrieval_strategy 表原记录
    // data.form.id 不存在说明是新增模式，后端会插入一条新策略记录
    const action = data.form.id
        ? request.put('/retrievalStrategy/update', data.form)
        : request.post('/retrievalStrategy/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        data.formVisible = false
        load()
      } else {
        // 两路都关、开了改写没选方式、阈值越界，后端都返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/retrievalStrategy/delete/' + id).then(res => {
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
  // 清空搜索条件并回到第一页，再查一次完整列表
  data.name = ''
  data.pageNum = 1
  load()
}

// 页面加载时立刻查一次，进入页面就能看到第一页数据
load()
</script>
