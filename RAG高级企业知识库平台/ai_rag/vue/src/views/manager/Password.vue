<template>
  <div style="width: 50%" class="card">
    <el-form ref="formRef" :rules="data.rules" :model="data.user" label-width="80px" style="padding: 20px">
      <!-- 输入值存进 data.user.password，后端用它和数据库里的旧密码比对 -->
      <el-form-item label="原密码" prop="password">
        <el-input v-model="data.user.password" placeholder="请输入原密码" show-password></el-input>
      </el-form-item>
      <!-- 输入值存进 data.user.newPassword，校验通过后写进 user 表的 password 列 -->
      <el-form-item label="新密码" prop="newPassword">
        <el-input v-model="data.user.newPassword" placeholder="请输入新密码" show-password></el-input>
      </el-form-item>
      <!-- 只在前端校验一致性，不发给后端参与业务判断 -->
      <el-form-item label="确认密码" prop="confirmPassword">
        <el-input v-model="data.user.confirmPassword" placeholder="请确认新密码" show-password></el-input>
      </el-form-item>
      <div style="text-align: center">
        <el-button type="primary" @click="updatePassword">保 存</el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup>
import {reactive, ref} from "vue";
import request from "@/utils/request.js";
import {ElMessage} from "element-plus";
import router from "@/router/index.js";

const formRef = ref()

// 确认密码要和新密码比对，用自定义校验函数实现，
// 传 Error 给 callback 表示不通过，不传参表示通过
const validatePass = (rule, value, callback) => {
  if (!value) {
    callback(new Error('请确认密码'))
    return
  }
  // data.user.newPassword 是上面新密码框的值，两次输入不一致就在输入框下方红字提示
  if (value !== data.user.newPassword) {
    callback(new Error('确认密码跟新密码不一致!'))
    return
  }
  callback()
}

const data = reactive({
  // 从登录缓存里取当前用户，后面把 password、newPassword、confirmPassword
  // 三个输入框的值挂到这同一个对象上，整体作为请求体提交
  user: JSON.parse(localStorage.getItem('xm-user') || '{}'),
  // 三项都必填，其中确认密码用自定义函数校验一致性
  rules: {
    password: [
      { required: true, message: '请输入原密码', trigger: 'blur' },
    ],
    newPassword: [
      { required: true, message: '请输入新密码', trigger: 'blur' },
    ],
    confirmPassword: [
      { validator: validatePass, trigger: 'blur' }
    ]
  }
})

const updatePassword = () => {
  formRef.value.validate(valid => {
    // valid 为 true 表示三个框都填了、且两次新密码一致
    if (valid) {
      // 当前登录用户从 token 解析，接口不需要传用户 id
      request.put('/updatePassword', data.user).then(res => {
        if (res.code === '200') {
          ElMessage.success('保存成功')
          // 密码变了，手上这个 token 对应的还是旧密码时期的登录状态，
          // 清掉缓存回登录页，用新密码重新登录
          logout()
        } else {
          // 原密码错误、新密码与原密码相同这些业务失败，后端在 msg 里返回人话提示
          ElMessage.error(res.msg)
        }
      })
    }
  })
}

const logout = () => {
  // 清掉本地登录缓存，request.js 之后取不到 token，回到未登录状态
  localStorage.removeItem('xm-user')
  router.push('/login')
}
</script>

<style scoped>

</style>