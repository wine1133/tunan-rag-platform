<template>
  <!-- 用户端页脚。做成单行紧凑版，高度控制在 56px 左右，
       和 Home.vue 里 calc(100vh - 150px) 的高度预算对得上，不会把页面撑出滚动条 -->
  <div class="front-footer">
    <div class="footer-inner">
      <div class="footer-left">
        <img src="@/assets/imgs/logo.png" alt="">
        <span class="footer-name">兔南高级企业知识库RAG平台</span>
        <span class="footer-sep">·</span>
        <span class="footer-org">广联智造股份有限公司</span>
      </div>
      <div class="footer-right">
        <span>服务热线 400-820-9600</span>
        <span class="footer-sep">|</span>
        <span>技术支持 support@glzz.com</span>
        <span class="footer-sep">|</span>
        <span>© 2026 保留所有权利</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.front-footer {
  border-top: 1px solid #e6e9f0;
  background-color: #fafbfd;
}

.footer-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 92%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 16px 0;
  font-size: 12px;
  color: #9096a3;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.footer-left img {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

.footer-name {
  font-size: 13px;
  font-weight: 600;
  color: #4b5563;
}

.footer-sep {
  color: #d3d8e3;
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 窄屏改成上下两行居中，右侧那串信息允许换行 */
@media (max-width: 760px) {
  .footer-inner {
    flex-direction: column;
    gap: 8px;
    text-align: center;
  }

  .footer-right {
    flex-wrap: wrap;
    justify-content: center;
  }
}
</style>
