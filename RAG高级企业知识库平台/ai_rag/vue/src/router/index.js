import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/login' },
    {
      path: '/manager',
      component: () => import('@/views/Manager.vue'),
      children: [
        { path: 'home', meta: { name: '系统首页' }, component: () => import('@/views/manager/Home.vue'),  },
        { path: 'user', meta: { name: '用户管理', requiresAdmin: true }, component: () => import('@/views/manager/User.vue'), },
        // 知识库是企业资料的一级分类，只有管理员能维护
        { path: 'knowledgeBase', meta: { name: '知识库管理', requiresAdmin: true }, component: () => import('@/views/manager/KnowledgeBase.vue'), },
        // 知识文档挂在知识库下，只有管理员能上传和删除
        { path: 'knowledgeDocument', meta: { name: '文档管理', requiresAdmin: true }, component: () => import('@/views/manager/KnowledgeDocument.vue'), },
        // 切分策略决定文档怎么切成片段
        { path: 'chunkStrategy', meta: { name: '切分策略', requiresAdmin: true }, component: () => import('@/views/manager/ChunkStrategy.vue'), },
        // 知识片段是检索的最小单位，支持人工修正
        { path: 'knowledgeChunk', meta: { name: '片段管理', requiresAdmin: true }, component: () => import('@/views/manager/KnowledgeChunk.vue'), },
        // 输入一个问题，看这套检索策略召回了哪些片段
        { path: 'retrievalTest', meta: { name: '检索测试', requiresAdmin: true }, component: () => import('@/views/manager/RetrievalTest.vue'), },
        // 一整套检索参数的管理页
        { path: 'retrievalStrategy', meta: { name: '检索策略', requiresAdmin: true }, component: () => import('@/views/manager/RetrievalStrategy.vue'), },
        // 同一个问题多套策略并排跑，把效果差异摆在一起看
        { path: 'retrievalDebug', meta: { name: '召回调试台', requiresAdmin: true }, component: () => import('@/views/manager/RetrievalDebug.vue'), },
        // 三类模型的接入配置，改配置立刻生效不用重启
        { path: 'aiModelConfig', meta: { name: 'AI模型配置', requiresAdmin: true }, component: () => import('@/views/manager/AiModelConfig.vue'), },
        // 所有发给模型的提示词都在这里维护
        { path: 'promptTemplate', meta: { name: 'Prompt模板', requiresAdmin: true }, component: () => import('@/views/manager/PromptTemplate.vue'), },
        // Agent 能用哪些工具由这张表决定，启用开关是真开关
        { path: 'functionTool', meta: { name: '工具中心', requiresAdmin: true }, component: () => import('@/views/manager/FunctionTool.vue'), },
        // 每次工具调用都留一条日志，成功失败都记
        { path: 'toolCallLog', meta: { name: '工具调用日志', requiresAdmin: true }, component: () => import('@/views/manager/ToolCallLog.vue'), },
        // 输入一个问题，看 Agent 自己判断要不要重新检索
        { path: 'agentTest', meta: { name: 'Agent执行', requiresAdmin: true }, component: () => import('@/views/manager/AgentTest.vue'), },
        // 运行记录列表和每一次运行的执行时间线
        { path: 'agentRun', meta: { name: 'Agent运行记录', requiresAdmin: true }, component: () => import('@/views/manager/AgentRun.vue'), },
        // 一个应用 = 一组知识库 + 一套检索策略 + 一种问答模式
        { path: 'qaApp', meta: { name: '问答应用', requiresAdmin: true }, component: () => import('@/views/manager/QaApp.vue'), },
        // 管理端直接对着应用提问，流式看答案
        { path: 'qaChat', meta: { name: '问答测试', requiresAdmin: true }, component: () => import('@/views/manager/QaChat.vue'), },
        // 所有会话记录和用户反馈，点踩的问题会进优化清单
        { path: 'chatLog', meta: { name: '对话日志与反馈', requiresAdmin: true }, component: () => import('@/views/manager/ChatLog.vue'), },
        // 评测集和用例，三个来源：手工录入、文档生成、反馈沉淀
        { path: 'evalDataset', meta: { name: '评测集管理', requiresAdmin: true }, component: () => import('@/views/manager/EvalDataset.vue'), },
        // 批量跑评测，用 LLM-as-judge 算四个指标
        { path: 'evalTask', meta: { name: '批量评测', requiresAdmin: true }, component: () => import('@/views/manager/EvalTask.vue'), },
        // 多份报告并排对比，横向看出每一步优化带来的分数变化
        { path: 'evalDashboard', meta: { name: '策略对比看板', requiresAdmin: true }, component: () => import('@/views/manager/EvalDashboard.vue'), },
        { path: 'person', meta: { name: '个人资料' }, component: () => import('@/views/manager/Person.vue'), },
        { path: 'password', meta: { name: '修改密码' }, component: () => import('@/views/manager/Password.vue'), },
        // 新路由
      ]
    },
    {
      path: '/front',
      component: () => import('@/views/Front.vue'),
      children: [
        { path: 'home', component: () => import('@/views/front/Home.vue'),  },
        // 个人中心展示和修改当前登录用户的资料，meta 上标 requiresLogin，
        // 由下面的守卫拦住未登录访问
        { path: 'person', meta: { requiresLogin: true }, component: () => import('@/views/front/Person.vue'),  },
      ]
    },
    { path: '/login', component: () => import('@/views/Login.vue') },
    { path: '/register', component: () => import('@/views/Register.vue') },
    { path: '/404', component: () => import('@/views/404.vue') },
    { path: '/:pathMatch(.*)', redirect: '/404' }
  ]
})

// 切换页面跳转到顶部
router.afterEach(() => {
  setTimeout(() => {
    window.scroll({ top: 0, behavior: 'smooth' })
  }, 0)
})

router.beforeEach((to) => {
  // 从登录时存下的缓存里取当前用户，没登录时取到空对象
  const user = JSON.parse(localStorage.getItem('xm-user') || '{}')
  // 管理端所有页面都要求先登录，没有 id 说明缓存里没有用户，打回登录页
  if (to.path.startsWith('/manager') && !user.id) {
    return '/login'
  }
  // 用户端只有标了 requiresLogin 的页面要求登录，首页对访客开放
  if (to.meta.requiresLogin && !user.id) {
    return '/login'
  }
  // 路由 meta 上标了 requiresAdmin 的页面只有管理员能进，
  // 普通用户误访问时退回管理端首页而不是白屏
  if (to.meta.requiresAdmin && user.role !== 'ADMIN') {
    return '/manager/home'
  }
})

export default router
