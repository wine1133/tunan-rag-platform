<template>
  <div style="width: 50%" class="card">
    <el-form ref="user" :model="data.user" label-width="70px" style="padding: 20px">
      <el-form-item prop="avatar" label="头像">
        <el-upload
            :action="baseUrl + '/files/upload'"
            :on-success="handleFileUpload"
            :show-file-list="false"
            class="avatar-uploader"
        >
          <img v-if="data.user.avatar" :src="data.user.avatar" class="avatar" />
          <el-icon v-else class="avatar-uploader-icon"><Plus /></el-icon>
        </el-upload>
      </el-form-item>
      <el-form-item prop="username" label="用户名">
        <el-input disabled v-model="data.user.username" placeholder="请输入用户名"></el-input>
      </el-form-item>
      <el-form-item prop="name" label="姓名">
        <el-input v-model="data.user.name" placeholder="请输入姓名"></el-input>
      </el-form-item>
      <el-form-item prop="phone" label="电话">
        <el-input v-model="data.user.phone" placeholder="请输入电话"></el-input>
      </el-form-item>
      <el-form-item prop="email" label="邮箱">
        <el-input v-model="data.user.email" placeholder="请输入邮箱"></el-input>
      </el-form-item>
      <div style="text-align: center">
        <el-button type="primary" @click="update">保 存</el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import request from "@/utils/request.js";
import {ElMessage} from "element-plus";

// 头像上传组件自己发请求，不走 request.js，action 需要完整地址
const baseUrl = import.meta.env.VITE_BASE_URL

const data = reactive({
  // 直接拿登录时存进 localStorage 的用户信息做表单初始值，
  // 里面已经有 id、username、name、phone、email、avatar，进页面不用再查一次接口
  user: JSON.parse(localStorage.getItem('xm-user') || '{}')
})

const handleFileUpload = (res) => {
  // 上传成功后后端返回的 res.data 是文件下载地址，写进 data.user.avatar，
  // 模板里的 img 立刻显示新头像，点保存后才真正写进 user 表
  data.user.avatar = res.data
}

// 保存成功后要通知外层布局刷新右上角的头像和姓名，
// 外层 Manager.vue 在 RouterView 上监听了这个事件
const emit = defineEmits(['updateUser'])

const update = () => {
  // data.user 里带着 id，后端按 id 更新这条用户记录；
  // username 和 password 会被后端排除掉，改不了账号也改不了密码
  request.put('/user/update', data.user).then(res => {
    if (res.code === '200') {
      ElMessage.success('保存成功')
      // 数据库改完了，本地缓存也要同步，否则刷新页面又变回旧值
      localStorage.setItem('xm-user', JSON.stringify(data.user))
      // 触发外层重新从 localStorage 读用户，右上角头像姓名立刻更新
      emit('updateUser')
    } else {
      ElMessage.error(res.msg)
    }
  })
}
</script>

<style>
.avatar-uploader {
  height: 120px;
}
.avatar-uploader .avatar {
  width: 120px;
  height: 120px;
  display: block;
}
.avatar-uploader .el-upload {
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition: var(--el-transition-duration-fast);
}

.avatar-uploader .el-upload:hover {
  border-color: var(--el-color-primary);
}

.el-icon.avatar-uploader-icon {
  font-size: 28px;
  color: #8c939d;
  width: 120px;
  height: 120px;
  text-align: center;
}
</style>
