<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 选中的知识库存进 data.kbId，作为 kb_id 参数传给后端限定查询范围 -->
      <el-select v-model="data.kbId" clearable style="width: 200px; margin-right: 10px" placeholder="请选择知识库">
        <el-option v-for="kb in data.kbOptions" :key="kb.id" :label="kb.name" :value="kb.id"></el-option>
      </el-select>
      <!-- 输入的文档名称存进 data.name，作为 name 参数做模糊匹配 -->
      <el-input v-model="data.name" style="width: 200px; margin-right: 10px" placeholder="请输入文档名称查询"></el-input>
      <!-- 选中的解析状态存进 data.parseStatus，作为 parse_status 参数做精确匹配 -->
      <el-select v-model="data.parseStatus" clearable style="width: 160px; margin-right: 10px" placeholder="请选择解析状态">
        <el-option label="待解析" value="待解析"></el-option>
        <el-option label="解析中" value="解析中"></el-option>
        <el-option label="解析完成" value="解析完成"></el-option>
        <el-option label="解析失败" value="解析失败"></el-option>
      </el-select>
      <!-- 直接调 load，带上当前三个搜索条件重新查询 -->
      <el-button type="info" plain @click="load">查询</el-button>
      <!-- 清空搜索条件并回到第一页 -->
      <el-button type="warning" plain style="margin: 0 10px" @click="reset">重置</el-button>
    </div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 打开空白弹窗，走上传流程 -->
      <el-button type="primary" plain @click="handleAdd">上传文档</el-button>
      <!-- 删除表格里勾选中的多行 -->
      <el-button type="danger" plain @click="delBatch">批量删除</el-button>
    </div>

    <div class="card" style="margin-bottom: 5px">
      <!-- data.tableData 来自 /knowledgeDocument/selectPage 返回的 list -->
      <el-table stripe :data="data.tableData" @selection-change="handleSelectionChange">
        <!-- 多选列，配合批量删除使用 -->
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" label="文档名称" min-width="180" show-overflow-tooltip />
        <!-- kb_name 由后端按 kb_id 查知识库表得到，不是文档表自己的列 -->
        <el-table-column prop="kb_name" label="所属知识库" width="150" />
        <el-table-column prop="file_type" label="类型" width="90" />
        <!-- file_size 存的是字节数，前端转成 KB / MB 显示 -->
        <el-table-column prop="file_size" label="大小" width="100">
          <template #default="scope">{{ formatSize(scope.row.file_size) }}</template>
        </el-table-column>
        <!-- 解析状态由第 07 章的解析动作流转，这里只读展示 -->
        <el-table-column prop="parse_status" label="解析状态" width="110">
          <template #default="scope">
            <el-tag :type="parseStatusType(scope.row.parse_status)">{{ scope.row.parse_status }}</el-tag>
          </template>
        </el-table-column>
        <!-- 向量化状态由第 12 章的向量化动作流转，这里只读展示 -->
        <el-table-column prop="vector_status" label="向量化状态" width="120" />
        <!-- 解析出的字符数，解析完成后才有值 -->
        <el-table-column prop="char_count" label="字符数" width="90" />
        <!-- 解析时抽到过表格或走过 OCR 的文档打标记，一眼看出哪些是复杂文档 -->
        <el-table-column label="解析特征" width="130">
          <template #default="scope">
            <el-tag v-if="scope.row.has_table === '是'" type="warning" size="small">表格</el-tag>
            <el-tag v-if="scope.row.has_ocr === '是'" type="danger" size="small" style="margin-left: 4px">OCR</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="上传时间" width="180" />
        <!-- 切分出的片段数，第 09 章切分后才有值 -->
        <el-table-column prop="chunk_count" label="片段数" width="90" />
        <!-- 操作列全部用图标按钮，鼠标悬停由 el-tooltip 给出文字说明。
             禁用状态的按钮本身不触发鼠标事件，外面套一层 span 让提示照常弹出 -->
        <el-table-column label="操作" width="272" fixed="right" class-name="action-cell">
          <template #default="scope">
            <!-- 触发后端解析，解析中禁用按钮防止重复点击 -->
            <el-tooltip content="解析文档" placement="top">
              <span class="action-btn">
                <el-button
                    type="primary"
                    circle
                    plain
                    size="small"
                    :icon="MagicStick"
                    :disabled="scope.row.parse_status === '解析中'"
                    @click="parseDoc(scope.row.id)"
                ></el-button>
              </span>
            </el-tooltip>
            <!-- 解析完成后才能看文本，没解析过时不显示这个按钮 -->
            <el-tooltip v-if="scope.row.parse_status === '解析完成'" content="查看解析文本" placement="top">
              <el-button
                  type="info"
                  circle
                  plain
                  size="small"
                  :icon="View"
                  @click="viewText(scope.row.id)"
              ></el-button>
            </el-tooltip>
            <!-- 切分依赖解析结果，解析完成后才显示这个按钮 -->
            <el-tooltip v-if="scope.row.parse_status === '解析完成'" content="切分片段" placement="top">
              <el-button
                  type="primary"
                  circle
                  plain
                  size="small"
                  :icon="Scissor"
                  @click="openSplit(scope.row)"
              ></el-button>
            </el-tooltip>
            <!-- 向量化依赖切分结果，有片段才显示；向量化中禁用，防止重复触发 -->
            <el-tooltip v-if="scope.row.chunk_count > 0" content="向量化" placement="top">
              <span class="action-btn">
                <el-button
                    type="primary"
                    circle
                    plain
                    size="small"
                    :icon="Cpu"
                    :disabled="scope.row.vector_status === '向量化中'"
                    @click="vectorize(scope.row)"
                ></el-button>
              </span>
            </el-tooltip>
            <!-- 向量化过的文档才需要清除向量 -->
            <el-tooltip
                v-if="scope.row.vector_status === '已完成' || scope.row.vector_status === '失败'"
                content="清除向量"
                placement="top"
            >
              <el-button
                  type="warning"
                  circle
                  plain
                  size="small"
                  :icon="Brush"
                  @click="clearVectors(scope.row)"
              ></el-button>
            </el-tooltip>
            <!-- 在新标签页打开文件地址，直接看原始文件 -->
            <el-tooltip content="下载原文件" placement="top">
              <el-button
                  type="success"
                  circle
                  plain
                  size="small"
                  :icon="Download"
                  @click="download(scope.row.file_url)"
              ></el-button>
            </el-tooltip>
            <!-- 把当前行数据带进弹窗，走编辑流程 -->
            <el-tooltip content="编辑" placement="top">
              <el-button
                  type="primary"
                  circle
                  plain
                  size="small"
                  :icon="Edit"
                  @click="handleEdit(scope.row)"
              ></el-button>
            </el-tooltip>
            <!-- 只把当前行的 id 传给删除方法 -->
            <el-tooltip content="删除" placement="top">
              <el-button
                  type="danger"
                  circle
                  plain
                  size="small"
                  :icon="Delete"
                  @click="del(scope.row.id)"
              ></el-button>
            </el-tooltip>
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

    <!-- 上传和编辑共用这一个弹窗，destroy-on-close 保证每次打开都是全新的表单 -->
    <el-dialog title="知识文档" v-model="data.formVisible" width="45%" destroy-on-close>
      <el-form ref="formRef" :model="data.form" :rules="data.rules" label-width="100px" style="padding: 20px">
        <!-- 选中的知识库 id 存进 data.form.kb_id，保存时决定这篇文档挂到哪个库 -->
        <el-form-item label="所属知识库" prop="kb_id">
          <el-select v-model="data.form.kb_id" style="width: 100%" placeholder="请选择知识库">
            <el-option v-for="kb in data.kbOptions" :key="kb.id" :label="kb.name" :value="kb.id"></el-option>
          </el-select>
        </el-form-item>
        <!-- 上传成功后触发 handleFileUpload，把地址、文件名、大小一起回填进表单 -->
        <el-form-item label="文档文件" prop="file_url">
          <el-upload
              :action="baseUrl + '/files/upload'"
              :on-success="handleFileUpload"
              :limit="1"
              accept=".pdf,.docx,.doc,.xlsx,.xls,.md,.txt"
          >
            <el-button type="primary">点击上传</el-button>
            <template #tip>
              <div style="color: #999; font-size: 12px">支持 PDF、Word、Excel、Markdown、TXT</div>
            </template>
          </el-upload>
        </el-form-item>
        <!-- 已选文件名，上传成功后显示，让用户确认传对了文件 -->
        <el-form-item label="已选文件" v-if="data.form.file_name">
          <span>{{ data.form.file_name }}</span>
        </el-form-item>
        <!-- 留空时后端会用上传的文件名顶上 -->
        <el-form-item label="文档名称">
          <el-input v-model="data.form.name" placeholder="不填时默认使用上传的文件名"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
      </template>
    </el-dialog>

    <!-- 切分弹窗，让管理员在切分前挑一套策略 -->
    <el-dialog title="切分文档" v-model="data.splitVisible" width="35%" destroy-on-close>
      <el-form label-width="100px" style="padding: 10px 20px">
        <el-form-item label="文档">
          <span>{{ data.splitDoc.name }}</span>
        </el-form-item>
        <!-- 不选时后端按"知识库绑定的策略 > 全局默认策略"的顺序兜底 -->
        <el-form-item label="切分策略">
          <el-select v-model="data.splitStrategyId" clearable style="width: 100%" placeholder="不选则使用默认策略">
            <el-option
                v-for="item in data.strategyOptions"
                :key="item.id"
                :label="item.name + '（' + item.strategy_type + ' ' + item.chunk_size + '字）'"
                :value="item.id"
            ></el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="data.splitVisible = false">取消</el-button>
        <el-button type="primary" @click="doSplit">开始切分</el-button>
      </template>
    </el-dialog>

    <!-- 查看解析文本弹窗，内容来自 /knowledgeDocument/parsedText/{id} -->
    <el-dialog title="解析结果" v-model="data.textVisible" width="60%" destroy-on-close>
      <div style="margin-bottom: 10px">
        <span style="margin-right: 20px">字符数：{{ data.textDetail.char_count }}</span>
        <el-tag v-if="data.textDetail.has_table === '是'" type="warning" size="small">含表格</el-tag>
        <el-tag v-if="data.textDetail.has_ocr === '是'" type="danger" size="small" style="margin-left: 6px">走过OCR</el-tag>
      </div>
      <!-- 解析文本可能很长，固定高度加滚动条；white-space 保留换行和表格的排版 -->
      <div style="max-height: 500px; overflow: auto; background: #f7f7f7; padding: 12px; white-space: pre-wrap; font-size: 13px">{{ data.textDetail.parsed_text }}</div>
      <template #footer>
        <el-button @click="data.textVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { Brush, Cpu, Delete, Download, Edit, MagicStick, Scissor, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

// 文件上传组件自己发请求，不走 request.js，action 需要完整地址
const baseUrl = import.meta.env.VITE_BASE_URL

const data = reactive({
  // 控制文档弹窗的显示隐藏，上传和编辑复用同一个弹窗
  formVisible: false,
  // 弹窗里各字段绑定的对象。有 id 表示编辑，没有 id 表示新增
  form: {},
  // 表格数据，由 /knowledgeDocument/selectPage 返回的 list 填充
  tableData: [],
  // 知识库下拉选项，来自 /knowledgeBase/selectAll，搜索栏和弹窗共用这一份
  kbOptions: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  // 顶部知识库下拉框的值，作为 kb_id 参数限定查询范围
  kbId: '',
  // 顶部文档名称搜索框的值
  name: '',
  // 顶部解析状态下拉框的值
  parseStatus: '',
  // 表格勾选中的行 id 集合，批量删除时提交它
  ids: [],
  // 控制查看解析文本弹窗的显示隐藏
  textVisible: false,
  // 解析结果详情，由 /knowledgeDocument/parsedText/{id} 填充
  textDetail: {},
  // 控制切分弹窗的显示隐藏
  splitVisible: false,
  // 当前要切分的那一行文档，弹窗上展示名称
  splitDoc: {},
  // 切分弹窗里选中的策略 id，为空表示让后端用默认策略
  splitStrategyId: '',
  // 切分策略下拉选项，来自 /chunkStrategy/selectAll
  strategyOptions: [],
  // 弹窗的前端校验规则，知识库和文件都必选
  rules: {
    kb_id: [
      { required: true, message: '请选择所属知识库', trigger: 'change' }
    ],
    file_url: [
      { required: true, message: '请先上传文件', trigger: 'change' }
    ]
  }
})

// formRef 绑定弹窗里的 el-form，点确定时触发整表校验
const formRef = ref()

const loadKbOptions = () => {
  // 只返回正常状态的知识库，停用的库不出现在下拉框里
  request.get('/knowledgeBase/selectAll').then(res => {
    if (res.code === '200') {
      data.kbOptions = res.data || []
    }
  })
}

const load = () => {
  // 分页查询接口，五个参数分别来自页码、每页条数、知识库下拉框、名称搜索框、解析状态下拉框
  request.get('/knowledgeDocument/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      kb_id: data.kbId || undefined,
      name: data.name,
      parse_status: data.parseStatus
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
  // 新增时给一份干净的表单，没有 id，save 时会走新增接口；
  // 如果顶部已经选了知识库，弹窗里默认带上，省一次选择
  data.form = { kb_id: data.kbId || undefined }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变；
  // 拷贝过来的对象带 id，save 时会走更新接口
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const handleFileUpload = (res, file) => {
  if (res.code !== '200') {
    ElMessage.error(res.msg)
    return
  }
  // res.data 是后端返回的下载地址，存进表单后保存时写进 knowledge_document.file_url
  data.form.file_url = res.data
  // 原始文件名，后端按它的后缀推断 file_type，决定第 07 章用哪个解析器
  data.form.file_name = file.name
  // 文件字节数，列表页展示时转成 KB / MB
  data.form.file_size = file.size
  // 文档名称没填过就用文件名顶上，用户可以再改
  if (!data.form.name) {
    data.form.name = file.name
  }
}

const save = () => {
  formRef.value.validate(valid => {
    // 知识库没选或文件没传时不发请求，表单项下方直接红字提示
    if (!valid) {
      return
    }
    // data.form.id 存在说明当前弹窗是编辑模式，后端按 id 更新 knowledge_document 表原记录
    // data.form.id 不存在说明是新增模式，后端会插入一条新文档记录并刷新知识库的文档数
    const action = data.form.id
        ? request.put('/knowledgeDocument/update', data.form)
        : request.post('/knowledgeDocument/add', data.form)
    action.then(res => {
      if (res.code === '200') {
        ElMessage.success('保存成功')
        // 关掉弹窗并重新查一次列表，让表格显示最新数据
        data.formVisible = false
        load()
      } else {
        // 知识库停用、文件类型不支持这些业务失败，后端在 msg 里返回人话提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    request.delete('/knowledgeDocument/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        // 删完重新查列表，同时知识库那边的文档数也已经被后端减掉了
        load()
      } else {
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
    request.delete('/knowledgeDocument/deleteBatch', { data: data.ids }).then(res => {
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

const parseDoc = (id) => {
  // 接口只把状态改成"解析中"就返回，真正的解析在后端后台任务里跑
  request.post('/knowledgeDocument/parse/' + id).then(res => {
    if (res.code === '200') {
      ElMessage.success('已开始解析，稍后刷新查看结果')
      // 立刻刷新一次，表格里这一行的解析状态变成蓝色"解析中"
      load()
    } else {
      // 文件不存在、正在解析中这些业务失败，后端在 msg 里返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const viewText = (id) => {
  // 解析文本存在 knowledge_document.parsed_text 列上，单独用一个接口取，
  // 不放进列表接口里，避免列表返回体过大
  request.get('/knowledgeDocument/parsedText/' + id).then(res => {
    if (res.code === '200') {
      data.textDetail = res.data
      data.textVisible = true
    } else {
      ElMessage.error(res.msg)
    }
  })
}

const loadStrategyOptions = () => {
  // 切分弹窗里的策略下拉数据，进页面时取一次
  request.get('/chunkStrategy/selectAll').then(res => {
    if (res.code === '200') {
      data.strategyOptions = res.data || []
    }
  })
}

const openSplit = (row) => {
  // 记下要切分哪一行，策略下拉默认留空，由后端按默认策略兜底
  data.splitDoc = row
  data.splitStrategyId = ''
  data.splitVisible = true
}

const doSplit = () => {
  // strategy_id 不传时后端按"知识库绑定策略 > 全局默认策略"的顺序选
  request.post('/knowledgeChunk/split/' + data.splitDoc.id, null, {
    params: { strategy_id: data.splitStrategyId || undefined }
  }).then(res => {
    if (res.code === '200') {
      ElMessage.success('已开始切分，稍后刷新查看片段数')
      data.splitVisible = false
      load()
    } else {
      // 没解析过、没有默认策略这些业务失败，后端在 msg 里返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const vectorize = (row) => {
  // 接口只把状态改成"向量化中"就返回，真正的模型调用在后端后台任务里分批跑
  request.post('/vectorize/document/' + row.id).then(res => {
    if (res.code === '200') {
      ElMessage.success('已开始向量化，稍后刷新查看向量化状态')
      // 立刻刷新一次，表格里这一行的向量化状态变成"向量化中"
      load()
    } else {
      // 没配向量模型、没填 Key、还没切分、换了向量模型，后端都返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const clearVectors = (row) => {
  // 清向量是为了换向量模型或重做，先确认一次
  ElMessageBox.confirm('清除后该文档需要重新向量化，确定继续吗？', '清除确认', { type: 'warning' }).then(() => {
    request.delete('/vectorize/document/' + row.id).then(res => {
      if (res.code === '200') {
        // res.data 里带着清掉了多少条向量
        ElMessage.success(res.data)
        load()
      } else {
        // 向量库连不上时后端会给出明确提示
        ElMessage.error(res.msg)
      }
    })
  })
}

const download = (url) => {
  // file_url 指向 /files/download/{文件名}，新开标签页由浏览器处理下载
  window.open(url)
}

const formatSize = (size) => {
  // file_size 列存的是字节数，按大小换算成更好读的单位
  if (!size) {
    return '-'
  }
  if (size < 1024) {
    return size + ' B'
  }
  if (size < 1024 * 1024) {
    return (size / 1024).toFixed(1) + ' KB'
  }
  return (size / 1024 / 1024).toFixed(1) + ' MB'
}

const parseStatusType = (status) => {
  // 解析完成绿色、解析失败红色、解析中蓝色、待解析灰色
  if (status === '解析完成') {
    return 'success'
  }
  if (status === '解析失败') {
    return 'danger'
  }
  if (status === '解析中') {
    return 'primary'
  }
  return 'info'
}

const reset = () => {
  // 清空三个搜索条件并回到第一页，再查一次完整列表
  data.kbId = ''
  data.name = ''
  data.parseStatus = ''
  data.pageNum = 1
  load()
}

// 页面加载时先取知识库和切分策略两份下拉数据，再查第一页文档
// 页面加载时先取知识库下拉数据，再查第一页文档
loadKbOptions()
loadStrategyOptions()
load()
</script>

<style scoped>
/* 包在禁用按钮外面的一层，让 el-tooltip 能收到鼠标事件，
   inline-block 保证它和其他图标按钮排在同一行 */
.action-btn {
  display: inline-block;
}

/* 八个图标按钮必须排在一行。.cell 是 el-table 内部渲染的，
   拿不到 scoped 的 data-v，选择器要写 :deep() 才命中 */
:deep(.action-cell .cell) {
  white-space: nowrap;
}

/* 图标按钮之间留一点间距，circle 按钮默认贴得很近 */
.el-button + .el-button,
.action-btn + .el-button,
.el-button + .action-btn,
.action-btn + .action-btn {
  margin-left: 6px;
}
</style>
