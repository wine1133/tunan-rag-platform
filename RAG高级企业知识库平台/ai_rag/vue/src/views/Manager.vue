<template>
  <div class="manager-container">
    <div class="manager-header">
      <div class="manager-header-left">
        <img src="@/assets/imgs/logo.png" alt="">
        <div class="title">兔南高级企业知识库RAG平台</div>
      </div>
      <div class="manager-header-center">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item :to="{ path: '/manager/home' }">首页</el-breadcrumb-item>
          <el-breadcrumb-item>{{ router.currentRoute.value.meta.name }}</el-breadcrumb-item>
        </el-breadcrumb>
      </div>
      <div class="manager-header-right">
        <el-dropdown style="cursor: pointer">
          <div class="user-box">
            <img :src="data.user.avatar" alt="">
            <span class="user-name">{{ data.user.name }}</span>
            <el-icon color="#98a2b3"><arrow-down /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="router.push('/manager/person')">个人资料</el-dropdown-item>
              <el-dropdown-item @click="router.push('/manager/password')">修改密码</el-dropdown-item>
              <el-dropdown-item @click="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    <!-- 下面部分开始 -->
    <div style="display: flex">
      <div class="manager-main-left">
        <!-- default-openeds 列出所有需要默认展开的子菜单 index，新增分组时要同步补上 -->
        <el-menu :default-active="router.currentRoute.value.path"
                 :default-openeds="['1', '2', '3', '4', '5', '6']"
                 router
        >
          <el-menu-item index="/manager/home">
            <el-icon><HomeFilled /></el-icon>
            <span>系统首页</span>
          </el-menu-item>
          <!-- 知识库相关的菜单，只有管理员可见 -->
          <el-sub-menu v-if="data.user.role === 'ADMIN'" index="1">
            <template #title>
              <el-icon><Menu /></el-icon>
              <span>知识库管理</span>
            </template>
            <el-menu-item index="/manager/knowledgeBase">知识库管理</el-menu-item>
            <el-menu-item index="/manager/chunkStrategy">切分策略</el-menu-item>
            <el-menu-item index="/manager/retrievalStrategy">检索策略</el-menu-item>
            <el-menu-item index="/manager/knowledgeDocument">文档管理</el-menu-item>
            <el-menu-item index="/manager/knowledgeChunk">片段管理</el-menu-item>
            <el-menu-item index="/manager/retrievalTest">检索测试</el-menu-item>
            <el-menu-item index="/manager/retrievalDebug">召回调试台</el-menu-item>
            <!-- 新菜单 -->
          </el-sub-menu>
          <!-- AI 相关的配置菜单，只有管理员可见 -->
          <el-sub-menu v-if="data.user.role === 'ADMIN'" index="4">
            <template #title>
              <el-icon><Menu /></el-icon>
              <span>AI 配置</span>
            </template>
            <el-menu-item index="/manager/aiModelConfig">AI模型配置</el-menu-item>
            <el-menu-item index="/manager/promptTemplate">Prompt模板</el-menu-item>
            <el-menu-item index="/manager/functionTool">工具中心</el-menu-item>
            <el-menu-item index="/manager/toolCallLog">工具调用日志</el-menu-item>
            <el-menu-item index="/manager/agentTest">Agent执行</el-menu-item>
            <el-menu-item index="/manager/agentRun">Agent运行记录</el-menu-item>
          </el-sub-menu>
          <!-- 问答应用相关的菜单，只有管理员可见 -->
          <el-sub-menu v-if="data.user.role === 'ADMIN'" index="5">
            <template #title>
              <el-icon><Menu /></el-icon>
              <span>问答应用</span>
            </template>
            <el-menu-item index="/manager/qaApp">应用管理</el-menu-item>
            <el-menu-item index="/manager/qaChat">问答测试</el-menu-item>
            <el-menu-item index="/manager/chatLog">对话日志与反馈</el-menu-item>
          </el-sub-menu>
          <!-- 效果评测相关的菜单，只有管理员可见 -->
          <el-sub-menu v-if="data.user.role === 'ADMIN'" index="6">
            <template #title>
              <el-icon><Menu /></el-icon>
              <span>效果评测</span>
            </template>
            <el-menu-item index="/manager/evalDataset">评测集管理</el-menu-item>
            <el-menu-item index="/manager/evalTask">批量评测</el-menu-item>
            <el-menu-item index="/manager/evalDashboard">策略对比看板</el-menu-item>
          </el-sub-menu>
          <el-sub-menu v-if="data.user.role === 'ADMIN'" index="2">
            <template #title>
              <el-icon><Menu /></el-icon>
              <span>用户管理</span>
            </template>
            <el-menu-item index="/manager/user">用户管理</el-menu-item>
          </el-sub-menu>
        </el-menu>
      </div>
      <div class="manager-main-right">
        <!-- 子页面保存个人资料后触发 updateUser，外层重新读缓存刷新右上角 -->
        <RouterView @updateUser="updateUser" />
      </div>
    </div>
    <!-- 下面部分结束 -->


  </div>
</template>

<script setup>
import { reactive } from "vue";
import router from "@/router/index.js";
import {ElMessage} from "element-plus";

const data = reactive({
  user: JSON.parse(localStorage.getItem('xm-user') || '{}')
})

const logout = () => {
  localStorage.removeItem('xm-user')
  router.push('/login')
}

const updateUser = () => {
  // 重新从 localStorage 读一次，右上角绑定的 data.user 变了，头像和姓名跟着重新渲染
  data.user =  JSON.parse(localStorage.getItem('xm-user') || '{}')
}

if (!data.user.id) {
  logout()
  ElMessage.error('请登录！')
}
</script>

<style scoped>
@import "@/assets/css/manager.css";
</style>
