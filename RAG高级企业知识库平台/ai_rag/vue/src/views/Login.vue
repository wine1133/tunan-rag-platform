<template>
  <div class="login-page">
    <div class="login-card">
      <!-- 左侧品牌区：讲清楚这个平台用到的核心技术，窄屏下整块隐藏 -->
      <div class="brand">
        <div class="brand-glow"></div>
        <div class="brand-inner">
          <div class="brand-logo">
            <img src="@/assets/imgs/logo.png" alt="">
            <span>兔南高级企业知识库RAG平台</span>
          </div>
          <h1 class="brand-title">让企业知识<br>真正被检索到</h1>
          <p class="brand-desc">从文档解析、混合检索到自动评测，一条 RAG 链路走完。</p>
          <ul class="brand-list">
            <li>向量 + BM25 混合检索，RRF 融合排名</li>
            <li>Rerank 重排，父子分块与元数据过滤</li>
            <li>Query 改写：多查询、指代消解、HyDE</li>
            <li>LangGraph 编排的 Agentic RAG，过程可回溯</li>
            <li>LLM-as-judge 四指标评测与策略对比</li>
          </ul>
          <div class="brand-tags">
            <span>FastAPI</span>
            <span>LangChain</span>
            <span>LangGraph</span>
            <span>PGVector</span>
            <span>Vue 3</span>
          </div>
        </div>
      </div>

      <!-- 右侧表单区 -->
      <div class="login-panel">
        <div class="login-box">
          <div class="login-title">欢迎回来</div>
          <div class="login-subtitle">请登录你的账号</div>
          <el-form ref="formRef" :model="data.form" :rules="data.rules">
            <!-- prop="username" 对应 data.rules 里的 username 规则，输入值存进 data.form.username -->
            <el-form-item prop="username">
              <el-input :prefix-icon="User" size="large" v-model="data.form.username" placeholder="请输入账号"></el-input>
            </el-form-item>
            <!-- show-password 让密码框带小眼睛，输入值存进 data.form.password；
                 keyup.enter 让密码框里按回车等同于点登录按钮，走的是同一个 login 方法 -->
            <el-form-item prop="password">
              <el-input show-password :prefix-icon="Lock" size="large" v-model="data.form.password" placeholder="请输入密码"
                        @keyup.enter="login"></el-input>
            </el-form-item>
            <!-- 点击后触发 login 方法，先走表单校验再调登录接口 -->
            <el-form-item>
              <el-button class="login-btn" size="large" type="primary" @click="login">登 录</el-button>
            </el-form-item>
            <div class="login-tip">
              还没有账号？<a href="/register">立即注册</a>
            </div>
          </el-form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { User, Lock } from "@element-plus/icons-vue";
import request from "@/utils/request.js";
import {ElMessage} from "element-plus";
import router from "@/router/index.js";

const data = reactive({
  // form 存放两个输入框的值，通过 v-model 双向绑定，
  // 点登录时整个 form 对象作为请求体发给 POST /login
  form: {},
  // rules 是 Element Plus 表单的前端校验规则，
  // 拦住空账号空密码，减少一次无意义的接口请求
  rules: {
    username: [
      { required: true, message: '请输入账号', trigger: 'blur' }
    ],
    password: [
      { required: true, message: '请输入密码', trigger: 'blur' }
    ]
  }
})

// formRef 绑定模板上的 el-form，用来在点击按钮时触发整表校验
const formRef = ref()

const login = () => {
  formRef.value.validate(valid => {
    // valid 为 true 表示 rules 里的规则全部通过，才继续发请求
    if (valid) {
      // 把账号密码提交给后端的 account.py 登录接口
      request.post('/login', data.form).then(res => {
        if (res.code === '200') {
          ElMessage.success('登录成功')
          // res.data 里带着后端签发的 token 和当前用户信息，
          // 存进 localStorage 后，request.js 的请求拦截器每次都会把 token 放进请求头
          localStorage.setItem('xm-user', JSON.stringify(res.data))
          // 管理员进管理端，普通用户进用户端，
          // 这样普通用户登录后落在自己能用的页面上，而不是进到管理后台首页
          if (res.data.role === 'ADMIN') {
            router.push('/manager/home')
          } else {
            router.push('/front/home')
          }
        } else {
          // 账号密码错误、账号被停用这些业务失败，后端在 msg 里返回人话提示
          ElMessage.error(res.msg)
        }
      })
    }
  })
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  background-color: #eef1f7;
}

/* 整个登录区是一张固定尺寸的卡片，不铺满屏幕 */
.login-card {
  display: flex;
  width: 860px;
  height: 480px;
  border-radius: 14px;
  overflow: hidden;
  background-color: #fff;
  box-shadow: 0 18px 50px rgba(17, 24, 39, .14);
}

/* ---------- 左侧品牌区 ---------- */
.brand {
  position: relative;
  width: 440px;
  padding: 40px 38px;
  color: #fff;
  overflow: hidden;
  background: linear-gradient(150deg, #111827 0%, #1e293b 55%, #1e3a8a 100%);
}

/* 一团模糊光斑，给纯色背景加点层次，纯装饰 */
.brand-glow {
  position: absolute;
  width: 320px;
  height: 320px;
  top: -110px;
  right: -90px;
  border-radius: 50%;
  filter: blur(80px);
  opacity: .5;
  background: #2563eb;
  pointer-events: none;
}

.brand-inner {
  position: relative;
  z-index: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.brand-logo {
  display: flex;
  align-items: center;
  font-size: 14px;
  letter-spacing: 1px;
  color: rgba(255, 255, 255, .9);
}
.brand-logo img {
  width: 24px;
  height: 24px;
  margin-right: 9px;
  object-fit: contain;
}

.brand-title {
  margin: 26px 0 12px;
  font-size: 27px;
  line-height: 1.4;
  font-weight: 700;
  letter-spacing: 1px;
}

.brand-desc {
  margin: 0 0 22px;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(255, 255, 255, .6);
}

.brand-list {
  margin: 0;
  padding: 0;
  list-style: none;
  flex: 1;
}
.brand-list li {
  position: relative;
  padding-left: 18px;
  margin-bottom: 11px;
  font-size: 13px;
  line-height: 1.5;
  color: rgba(255, 255, 255, .76);
}
/* 用伪元素画小圆点，省一个图标依赖 */
.brand-list li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 7px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #60a5fa;
  box-shadow: 0 0 0 3px rgba(96, 165, 250, .2);
}

.brand-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.brand-tags span {
  padding: 3px 9px;
  border-radius: 4px;
  font-size: 11px;
  letter-spacing: .5px;
  color: rgba(255, 255, 255, .72);
  background-color: rgba(255, 255, 255, .1);
}

/* ---------- 右侧表单区 ---------- */
.login-panel {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 0 42px;
}

.login-box {
  width: 100%;
  max-width: 300px;
}

.login-title {
  font-size: 23px;
  font-weight: 700;
  color: #1f2937;
}

.login-subtitle {
  margin: 8px 0 26px;
  font-size: 13px;
  color: #9096a3;
}

.login-btn {
  width: 100%;
  margin-top: 4px;
  border: none;
  font-size: 15px;
  letter-spacing: 4px;
}

.login-tip {
  text-align: center;
  font-size: 13px;
  color: #9096a3;
}
.login-tip a {
  color: #2563eb;
  font-weight: 500;
}

.login-box :deep(.el-input__wrapper) {
  border-radius: 7px;
  padding: 1px 13px;
  box-shadow: 0 0 0 1px #e3e6ee inset;
}
.login-box :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #2563eb inset;
}

/* 窄屏只留表单，品牌区隐藏，卡片收窄 */
@media (max-width: 880px) {
  .brand {
    display: none;
  }
  .login-card {
    width: 380px;
    height: auto;
    padding: 30px 0;
  }
}
</style>
