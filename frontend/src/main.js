import { createApp, ref, onMounted, onUnmounted } from 'vue'
import './style.css'
const App = {
  setup() {
    const url = ref(''), busy = ref(false), imported = ref(false), importMessage = ref(''), listError = ref('')
    const subscriptionNodes = ref([]), listChecked = ref(false)
    const statsNodes = ref([]), hours = ref(24), selected = ref(null), history = ref([]), error = ref('')
    let timer
    async function request(path, options) {
      const r = await fetch(path, options)
      let data
      try { data = await r.json() } catch { throw new Error(`服务器返回 HTTP ${r.status}`) }
      if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${r.status}`)
      return data
    }
    async function importSubscription() {
      busy.value = true; importMessage.value = ''; listError.value = ''; listChecked.value = false; imported.value = false; subscriptionNodes.value = []
      try {
        const result = await request('/api/subscription/import', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({url:url.value}) })
        imported.value = true; importMessage.value = result.message
        url.value = '' // Do not retain the token in the text field after import
      } catch (e) { importMessage.value = '导入失败：' + e.message }
      finally { busy.value = false }
    }
    async function querySubscription() {
      listError.value = ''
      try {
        const result = await request('/api/subscription/nodes')
        subscriptionNodes.value = result.nodes; listChecked.value = true
      } catch (e) { listError.value = e.message }
    }
    async function loadStats() {
      try { statsNodes.value = await request(`/api/nodes?hours=${hours.value}`); error.value = '' }
      catch (e) { error.value = '采集 API 无法访问：' + e.message }
    }
    async function detail(n) {
      selected.value = n
      const q = new URLSearchParams({provider:n.provider,name:n.name,limit:30})
      try { history.value = await request('/api/history?' + q) } catch { history.value = [] }
    }
    onMounted(() => { loadStats(); timer = setInterval(loadStats,15000) })
    onUnmounted(() => clearInterval(timer))
    return {url,busy,imported,importMessage,listError,subscriptionNodes,listChecked,statsNodes,hours,selected,history,error,importSubscription,querySubscription,loadStats,detail}
  },
  template: `<main>
    <header><div class="eyebrow">NETWORK OBSERVABILITY / DAY 1</div><h1>Mihomo SLA Monitor</h1><p>订阅导入 → 节点查询 → SLA 探测</p></header>
    <section class="panel"><div class="sectiontop"><span class="step">01</span><div><h2>导入 Mihomo 订阅</h2><p>订阅由 Ubuntu 后端通过现有的 127.0.0.1:7890 代理获取，不在浏览器内下载。</p></div></div>
      <form class="importrow" @submit.prevent="importSubscription"><input type="url" v-model="url" placeholder="粘贴 HTTPS Mihomo YAML 订阅链接" autocomplete="off" spellcheck="false" required/><button :disabled="busy || !url.trim()">{{busy?'正在导入…':'导入订阅'}}</button></form>
      <p v-if="importMessage" :class="imported?'ok':'bad'" role="status">{{importMessage}}</p><p class="hint">密钥仅用于本次请求；节点凭据存于 Ubuntu 的 monitor/nodes.yaml，请勿公开 Web 服务。</p>
    </section>
    <section class="panel"><div class="sectiontop"><span class="step">02</span><div><h2>查询节点列表</h2><p>从监控 Mihomo API 查询实际加载的节点，而不是仅统计 YAML 中的条目。</p></div></div>
      <button class="secondary" @click="querySubscription">查询节点列表</button><span v-if="listChecked" class="count"> 已加载 {{subscriptionNodes.length}} 个节点</span><p v-if="listError" class="bad">{{listError}}</p>
      <div v-if="listChecked && subscriptionNodes.length" class="nodegrid"><div v-for="n in subscriptionNodes" :key="n.name" class="nodepill"><strong>{{n.name}}</strong><span>{{n.type}}</span></div></div>
      <p v-if="listChecked && !subscriptionNodes.length" class="bad">Provider 尚无可用节点，请检查订阅或稍后再次查询。</p>
    </section>
    <section class="panel"><div class="sectiontop"><span class="step">03</span><div><h2>SLA 探测记录</h2><p>定时采集所有节点的探测成功率与响应延迟，保存在 SQLite。</p></div></div>
      <div class="toolbar">统计窗口 <select v-model.number="hours" @change="loadStats"><option :value="1">1 小时</option><option :value="24">24 小时</option><option :value="168">7 天</option><option :value="720">30 天</option></select><button class="secondary" @click="loadStats">刷新统计</button><span class="error">{{error}}</span></div>
      <div class="summary">历史记录中的节点 <b>{{statsNodes.length}}</b><small>初次导入后等待约 60 秒生成探测数据</small></div>
      <div class="tablewrap"><table><thead><tr><th>节点</th><th>协议</th><th>样本</th><th>探测成功率</th><th>平均延迟</th><th>最近状态</th></tr></thead><tbody>
      <tr v-for="n in statsNodes" :key="n.provider+'|'+n.name" @click="detail(n)"><td>{{n.name}}<small>{{n.provider}}</small></td><td>{{n.kind}}</td><td>{{n.samples}}</td><td>{{n.availability_pct===null?'—':n.availability_pct+'%'}}</td><td>{{n.avg_ms===null?'—':n.avg_ms+' ms'}}</td><td :class="n.last_success===1?'ok':'bad'">{{n.last_success===1?'成功':n.last_success===0?'失败':'未探测'}}</td></tr>
      </tbody></table></div>
      <div v-if="selected" class="detail"><h3>{{selected.name}} · 最近 30 次探测</h3><div class="samples"><span v-for="(p,i) in history" :key="i" :title="p.checked_at+' | '+(p.error||p.latency_ms+' ms')" :class="p.success?'pass':'fail'"></span></div></div>
    </section>
    <footer>仅计算已完成样本的探测成功率，并非合同 SLA。管理界面默认只允许通过本地 SSH 隧道访问。</footer>
  </main>`
}
createApp(App).mount('#app')
