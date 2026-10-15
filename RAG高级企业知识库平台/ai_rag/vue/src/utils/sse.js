/**
 * SSE 流式请求。
 *
 * 浏览器原生的 EventSource 只支持 GET，也没法自定义请求头，
 * 而本项目的问答接口是 POST 且要带 token，所以用 fetch 读流自己解析 SSE 协议。
 *
 * SSE 的报文格式是一段一段的，段与段之间用空行隔开：
 *
 *     event: delta
 *     data: {"text":"质"}
 *
 *     event: delta
 *     data: {"text":"保"}
 */
import { ElMessage } from 'element-plus'

const baseUrl = import.meta.env.VITE_BASE_URL

/**
 * 发起一次流式问答。
 *
 * @param {string} path     接口路径，例如 /qaApp/ask
 * @param {object} body     请求体
 * @param {function} onEvent 每收到一个完整事件回调一次，参数是 (事件名, 解析后的数据)
 */
export async function streamPost(path, body, onEvent) {
  // token 从登录时存下的缓存里取，和 request.js 的请求拦截器同一个来源
  const user = JSON.parse(localStorage.getItem('xm-user') || '{}')
  const response = await fetch(baseUrl + path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json;charset=utf-8',
      token: user.token || ''
    },
    body: JSON.stringify(body)
  })
  if (!response.ok) {
    ElMessage.error('请求失败，请查看后端控制台报错')
    return
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  // 上一次读到一半的残缺报文，和这次读到的拼起来再解析
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    // SSE 协议允许 \r\n、\n、\r 三种换行，sse-starlette 发出来的是 \r\n。
    // 先统一成 \n 再按空行切分，否则 \r\n\r\n 分隔的报文一个都切不出来，
    // 页面上收不到任何事件，而后端其实已经正常跑完并把消息落库了
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, '\n')
    // 空行是一个事件的结束标志，按它切分
    const blocks = buffer.split('\n\n')
    // 最后一块可能是残缺的，留到下一轮再拼
    buffer = blocks.pop()
    for (const block of blocks) {
      const parsed = parseBlock(block)
      if (parsed) {
        onEvent(parsed.event, parsed.data)
      }
    }
  }
}

/**
 * 把一段 SSE 报文解析成事件名和数据。
 */
function parseBlock(block) {
  let event = 'message'
  const dataLines = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // 一个事件的 data 可能有多行，按协议要拼起来
      dataLines.push(line.slice(5).trim())
    }
  }
  if (!dataLines.length) {
    return null
  }
  try {
    return { event, data: JSON.parse(dataLines.join('')) }
  } catch (error) {
    // 后端发的不是合法 JSON 时跳过这一段，不让整个流断掉
    return null
  }
}
