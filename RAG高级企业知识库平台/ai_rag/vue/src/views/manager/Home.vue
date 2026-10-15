<template>
  <div>
    <div class="card">您好！{{ data.user?.name }}，欢迎使用本系统！</div>
  </div>
</template>

<script setup>

import {reactive} from "vue";

const data = reactive({
  user: JSON.parse(localStorage.getItem('xm-user') || '{}')
})
</script>
