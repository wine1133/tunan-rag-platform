<template>
  <div>
    <div class="card" style="margin-bottom: 5px">
      <!-- 输入的姓名存进 data.name，点查询时作为 name 参数传给后端做模糊匹配 -->
      <el-input v-model="data.name" style="width: 240px; margin-right: 10px" placeholder="请输入姓名查询"></el-input>
      <!-- 选中的角色存进 data.role，作为 role 参数传给后端做精确匹配；clearable 清空后表示不限角色 -->
      <el-select v-model="data.role" clearable style="width: 180px; margin-right: 10px" placeholder="请选择角色">
        <el-option label="管理员" value="ADMIN"></el-option>
        <el-option label="普通用户" value="USER"></el-option>
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
      <!-- data.tableData 来自 /user/selectPage 返回的 list；勾选变化时把选中行 id 存进 data.ids -->
      <el-table stripe :data="data.tableData" @selection-change="handleSelectionChange">
        <!-- 多选列，配合批量删除使用 -->
        <el-table-column type="selection" width="55" />
        <el-table-column prop="username" label="账号" />
        <!-- avatar 存的是文件下载地址，为空时不渲染图片，避免出现裂图 -->
        <el-table-column prop="avatar" label="头像" width="80">
          <template #default="scope">
            <el-image
                v-if="scope.row.avatar"
                style="width: 40px; height: 40px; border-radius: 50%; display: block"
                :src="scope.row.avatar"
                :preview-src-list="[scope.row.avatar]"
                preview-teleported
            ></el-image>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="姓名" />
        <!-- 表里存的是 ADMIN / USER，展示时翻译成中文 -->
        <el-table-column prop="role" label="角色">
          <template #default="scope">
            {{ scope.row.role === 'ADMIN' ? '管理员' : '普通用户' }}
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="电话" />
        <el-table-column prop="email" label="邮箱" />
        <!-- 表里存的是 NORMAL / DISABLED，正常显示绿标签，停用显示红标签 -->
        <el-table-column prop="status" label="状态">
          <template #default="scope">
            <el-tag :type="scope.row.status === 'NORMAL' ? 'success' : 'danger'">
              {{ scope.row.status === 'NORMAL' ? '正常' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
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
    <!-- data.total 为 0 时整个分页条不渲染，避免空列表下方出现孤零零的分页 -->
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
    <el-dialog title="用户信息" v-model="data.formVisible" width="40%" destroy-on-close>
      <el-form :model="data.form" label-width="70px" style="padding: 20px">
        <!-- 编辑时 data.form.id 有值，账号输入框禁用，因为后端 update 接口不接受修改账号 -->
        <el-form-item label="账号">
          <el-input v-model="data.form.username" placeholder="请输入账号" :disabled="data.form.id !== undefined"></el-input>
        </el-form-item>
        <!-- 只有新增时才显示密码框，编辑时后端 update 接口不处理密码，改密码走个人中心 -->
        <el-form-item v-if="!data.form.id" label="密码">
          <el-input v-model="data.form.password" show-password placeholder="不填写时默认密码为123456"></el-input>
        </el-form-item>
        <!-- 上传成功后触发 handleFileUpload，把返回的下载地址写进 data.form.avatar -->
        <el-form-item label="头像">
          <el-upload :action="baseUrl + '/files/upload'" :on-success="handleFileUpload" list-type="picture">
            <el-button type="primary">点击上传</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="data.form.name" placeholder="请输入姓名"></el-input>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="data.form.role" style="width: 100%">
            <el-option label="管理员" value="ADMIN"></el-option>
            <el-option label="普通用户" value="USER"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="data.form.phone" placeholder="请输入电话"></el-input>
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="data.form.email" placeholder="请输入邮箱"></el-input>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="data.form.status">
            <el-radio value="NORMAL">正常</el-radio>
            <el-radio value="DISABLED">停用</el-radio>
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
import { reactive } from 'vue'
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request.js'

// 头像上传组件的 action 需要完整地址，不走 request.js，所以单独取一次接口根地址
const baseUrl = import.meta.env.VITE_BASE_URL

const data = reactive({
  // 控制用户信息弹窗的显示隐藏，新增和编辑复用同一个弹窗
  formVisible: false,
  // 弹窗里各输入框绑定的对象。有 id 表示编辑，没有 id 表示新增
  form: {},
  // 表格数据，由 /user/selectPage 返回的 list 填充
  tableData: [],
  // 当前页码，分页组件切换页码时更新它并重新查询
  pageNum: 1,
  // 每页条数，固定 10 条
  pageSize: 10,
  // 总条数，决定分页条显示几页，为 0 时整个分页条不渲染
  total: 0,
  // 顶部姓名搜索框的值，作为查询参数传给后端做模糊匹配
  name: '',
  // 顶部角色下拉框的值，作为查询参数传给后端做精确匹配
  role: '',
  // 表格勾选中的行 id 集合，批量删除时提交它
  ids: []
})

const load = () => {
  // 分页查询接口，四个参数分别来自页码、每页条数、姓名搜索框、角色下拉框
  request.get('/user/selectPage', {
    params: {
      page_num: data.pageNum,
      page_size: data.pageSize,
      name: data.name,
      role: data.role
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
  // 角色默认普通用户、状态默认正常，和后端 add 的默认值保持一致
  data.form = { role: 'USER', status: 'NORMAL' }
  data.formVisible = true
}

const handleEdit = (row) => {
  // 深拷贝当前行，避免直接改 tableData 里的对象导致弹窗一改表格就跟着变；
  // 拷贝过来的对象带 id，save 时会走更新接口
  data.form = JSON.parse(JSON.stringify(row))
  data.formVisible = true
}

const save = () => {
  // data.form.id 存在说明当前弹窗是编辑模式，后端按 id 更新 user 表原记录
  // data.form.id 不存在说明是新增模式，后端会插入一条新用户记录
  const action = data.form.id
      ? request.put('/user/update', data.form)
      : request.post('/user/add', data.form)
  action.then(res => {
    if (res.code === '200') {
      ElMessage.success('保存成功')
      // 关掉弹窗并重新查一次列表，让表格显示最新数据
      data.formVisible = false
      load()
    } else {
      // 账号重复、角色参数错误这些业务失败，后端在 msg 里返回人话提示
      ElMessage.error(res.msg)
    }
  })
}

const del = (id) => {
  // 删除前先弹确认框，用户点取消时 Promise 不进入 then，不会发请求
  ElMessageBox.confirm('删除后数据无法恢复，您确定删除吗？', '删除确认', { type: 'warning' }).then(() => {
    // id 拼在路径上，后端用路径参数接收
    request.delete('/user/delete/' + id).then(res => {
      if (res.code === '200') {
        ElMessage.success('删除成功')
        // 删完重新查列表，被删的行从表格里消失
        load()
      } else {
        // 删除当前登录账号会被后端拦下来，提示在 msg 里
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
    request.delete('/user/deleteBatch', { data: data.ids }).then(res => {
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

const handleFileUpload = (res) => {
  // 上传成功后后端返回的 res.data 是文件下载地址，回填到表单的头像字段，
  // 点确定保存时这个地址会写进 user 表的 avatar 列
  data.form.avatar = res.data
}

const reset = () => {
  // 清空两个搜索条件并回到第一页，再查一次完整列表
  data.name = ''
  data.role = ''
  data.pageNum = 1
  load()
}

// 页面加载时立刻查一次，进入页面就能看到第一页数据
load()
</script>
