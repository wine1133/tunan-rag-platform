<template>
  <!-- 模型返回的答案是 Markdown 文本，这里渲染成 HTML 再显示；
       content 变化时 html 会重新计算，所以流式输出过程中也能边收边渲染 -->
  <div class="md-body" v-html="html"></div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({
  // 要渲染的 Markdown 原文，来自问答接口返回的答案
  content: {
    type: String,
    default: ''
  }
})

// gfm 打开表格、删除线这些扩展语法；
// breaks 让单个换行也变成 <br>，模型输出的答案经常只用一个换行分行
marked.setOptions({ gfm: true, breaks: true })

const html = computed(() => {
  if (!props.content) {
    return ''
  }
  // 答案由大模型生成，属于不可控内容，转成 HTML 前先过一遍消毒，
  // 把 script、on 事件这类危险内容去掉，避免 v-html 带来 XSS
  return DOMPurify.sanitize(marked.parse(props.content))
})
</script>

<style scoped>
.md-body {
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}

/* 内容由 v-html 插入，不带 scoped 的 data-v 属性，样式要写在 :deep() 里 */
.md-body :deep(p) {
  margin: 0 0 8px;
}

.md-body :deep(p:last-child) {
  margin-bottom: 0;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 12px 0 8px;
  font-size: 15px;
  font-weight: 600;
}

.md-body :deep(h1:first-child),
.md-body :deep(h2:first-child),
.md-body :deep(h3:first-child) {
  margin-top: 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 0 0 8px;
  padding-left: 22px;
}

.md-body :deep(li) {
  margin-bottom: 4px;
}

.md-body :deep(li:last-child) {
  margin-bottom: 0;
}

/* 行内代码和代码块，答案里出现接口名、错误码时会用到 */
.md-body :deep(code) {
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 13px;
  font-family: Consolas, Monaco, monospace;
  background-color: rgba(125, 135, 155, .14);
}

.md-body :deep(pre) {
  margin: 0 0 8px;
  padding: 10px 12px;
  border-radius: 6px;
  overflow-x: auto;
  background-color: rgba(125, 135, 155, .14);
}

.md-body :deep(pre code) {
  padding: 0;
  background: none;
}

/* 答案里引用制度条款时常出现表格，给它补上边框 */
.md-body :deep(table) {
  margin: 0 0 8px;
  border-collapse: collapse;
  font-size: 13px;
}

.md-body :deep(th),
.md-body :deep(td) {
  padding: 5px 10px;
  border: 1px solid #dfe3ea;
}

.md-body :deep(th) {
  background-color: rgba(125, 135, 155, .1);
  font-weight: 600;
}

.md-body :deep(blockquote) {
  margin: 0 0 8px;
  padding: 2px 0 2px 10px;
  border-left: 3px solid #c7cedb;
  color: #6b7280;
}

.md-body :deep(a) {
  color: #2563eb;
}

.md-body :deep(hr) {
  margin: 10px 0;
  border: none;
  border-top: 1px solid #e6e9f0;
}

.md-body :deep(img) {
  max-width: 100%;
}
</style>
