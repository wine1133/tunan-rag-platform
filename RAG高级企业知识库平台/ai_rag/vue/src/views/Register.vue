<template>
  <div class="login-container">
    <div class="login-box">
      <div style="font-weight: bold; font-size: 24px; text-align: center; margin-bottom: 30px; color: #1450aa">欢 迎 注 册</div>
      <el-form ref="formRef" :model="data.form" :rules="data.rules">
        <!-- prop="username" 对应 data.rules 里的 username 规则，输入值存进 data.form.username -->
        <el-form-item prop="username">
          <el-input :prefix-icon="User" size="large" v-model="data.form.username" placeholder="请输入账号"></el-input>
        </el-form-item>
        <!-- 输入值存进 data.form.password，同时作为下面确认密码框的比对基准 -->
        <el-form-item prop="password">
          <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.password" placeholder="请输入密码"></el-input>
        </el-form-item>
        <!-- prop="confirmPassword" 对应自定义校验函数 validatePass，输入值存进 data.form.confirmPassword -->
        <el-form-item prop="confirmPassword">
          <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.confirmPassword" placeholder="请确认密码"></el-input>
        </el-form-item>
        <el-form-item>
          <!-- 点击后触发 register 方法，先走表单校验再调注册接口 -->
          <el-button size="large" type="primary" style="width: 100%" @click="register">注 册</el-button>
        </el-form-item>
        <div style="text-align: right">
          已有账号？请 <a href="/login">登录</a>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { User, Lock } from "@element-plus/icons-vue";
import request from "@/utils/request.js";
import {ElMessage} from "element-plus";
import router from "@/router/index.js";

// confirmPassword 这一项没有固定规则，用自定义校验函数比对它和 password 是否一致，
// 校验结果通过 callback 回传给 Element Plus：传 Error 表示不通过，不传参表示通过
const validatePass = (rule, value, callback) => {
  if (!value) {
    callback(new Error('请确认密码'))
    return
  }
  // data.form.password 是上面那个密码输入框的值，两次输入不一致就在输入框下方红字提示
  if (value !== data.form.password) {
    callback(new Error('确认密码跟原密码不一致!'))
    return
  }
  callback()
}

const data = reactive({
  // form 存放账号、密码、确认密码三个输入框的值，
  // 点注册时整个 form 对象作为请求体发给 POST /register
  form: { },
  // 前端先校验一遍，把空值和两次密码不一致挡在请求之前
  rules: {
    username: [
      { required: true, message: '请输入账号', trigger: 'blur' }
    ],
    password: [
      { required: true, message: '请输入密码', trigger: 'blur' }
    ],
    confirmPassword: [
        { validator: validatePass, trigger: 'blur' }
    ]
  }
})

// formRef 绑定模板上的 el-form，用来在点击按钮时触发整表校验
const formRef = ref()

const register = () => {
  formRef.value.validate(valid => {
    // valid 为 true 表示三个输入框都填了、且两次密码一致
    if (valid) {
      // 提交给后端的 account.py 注册接口，后端会再校验一次账号是否重复
      request.post('/register', data.form).then(res => {
        if (res.code === '200') {
          ElMessage.success('注册成功')
          // 注册接口只建账号不发 token，所以跳回登录页让用户重新登录
          router.push('/login')
        } else {
          // 账号重复、两次密码不一致这些业务失败，后端在 msg 里返回人话提示
          ElMessage.error(res.msg)
        }
      })
    }
  })
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(to top, #00467f, #a5cc82);
}
.login-box {
  width: 350px;
  padding: 30px;
  border-radius: 5px;
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
  background-color: rgba(255, 255, 255, 0.5);
}
</style>