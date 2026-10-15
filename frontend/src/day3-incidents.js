import { computed, ref, onMounted, onUnmounted } from 'vue'
import './day3.css'

const humanDuration = seconds => {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)} 分钟`
  return `${(seconds / 3600).toFixed(2)} 小时`
}
const timeText = value => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit' })
}
const names = { healthy:'正常', suspect:'疑似故障', down:'故障已确认', recovering:'待确认恢复', unknown:'数据未知', stale:'监控中断', no_data:'无监控数据', target_switch_pending:'检测目标切换中' }

export default {
  setup () {
    const hours = ref(24)
    const summary = ref(null)
    const nodes = ref([])
    const events = ref([])
    const error = ref('')
    const busy = ref(false)
    const lastRefresh = ref('')
    let clock = null
    let latestRequest = 0
    const selectedNode = ref('all')
    const asText = key => names[key] || key || '—'
    const displayedEvents = computed(() => selectedNode.value === 'all' ? events.value : events.value.filter(e => JSON.stringify([e.provider,e.name]) === selectedNode.value))
    const monitored = computed(() => summary.value?.monitor || null)
    const monitoringOk = computed(() => monitored.value?.status === 'healthy')
    const statuses = computed(() => ({
      down: nodes.value.filter(n => ['down','recovering'].includes(n.status)).length,
      suspect: nodes.value.filter(n => n.status === 'suspect').length,
      unknown: nodes.value.filter(n => n.status === 'unknown').length
    }))

    async function load() {
      const current = ++latestRequest
      busy.value = true
      error.value = ''
      try {
        const params = new URLSearchParams({ hours: String(hours.value) }).toString()
        const [s,n,e] = await Promise.all(['summary','nodes','events'].map(async endpoint => {
          const response = await fetch(`/api/incidents/${endpoint}?${params}`, {cache:'no-store'})
          if (!response.ok) throw new Error(`${endpoint} HTTP ${response.status}`)
          return response.json()
        }))
        if (current !== latestRequest) return
        summary.value = s
        nodes.value = n.nodes || []
        events.value = e.events || []
        lastRefresh.value = new Date().toLocaleTimeString('zh-CN')
      } catch (err) { if (current === latestRequest) error.value = `Day 3 数据获取失败：${err.message}` }
      finally { if (current === latestRequest) busy.value = false }
    }

    const incidentBar = incident => {
      const now = Date.now()
      const start = now - hours.value * 3600 * 1000
      const first = Date.parse(incident.started_at)
      const finish = incident.ended_at ? Date.parse(incident.ended_at) : now
      if (!Number.isFinite(first) || !Number.isFinite(finish)) return {display:'none'}
      const x = Math.max(start, first)
      const y = Math.min(now, finish)
      const left = Math.max(0, Math.min(100, (x - start) / (now - start) * 100))
      const width = Math.max(0.6, Math.min(100-left, Math.max(0, y-x)/(now-start)*100))
      return {left: `${left}%`, width:`${width}%`}
    }
    onMounted(() => { load(); clock = setInterval(load,30000) })
    onUnmounted(() => { clearInterval(clock); latestRequest++ })
    return {hours,summary,nodes,displayedEvents,error,busy,lastRefresh,selectedNode,asText,timeText,humanDuration,load,monitored,monitoringOk,statuses,incidentBar}
  },
  template: `
    <main class="day3-root">
      <section class="day3-panel">
        <div class="day3-top">
          <div><div class="day3-eyebrow">NETWORK OBSERVABILITY / DAY 3</div>
            <h2>故障事件与可靠性分析</h2>
            <p>连续失败 3 次确认故障 · 连续成功 2 次确认恢复 · 监控中断单独标识</p></div>
          <div class="day3-fresh" :class="monitoringOk?'good':'uncertain'">{{ asText(monitored?.status) }}<small v-if="lastRefresh">更新于 {{lastRefresh}}</small></div>
        </div>
        <div class="day3-toolbar">
          <label>统计窗口 <select v-model.number="hours" @change="load"><option :value="1">1 小时</option><option :value="24">24 小时</option><option :value="168">7 天</option><option :value="720">30 天</option></select></label>
          <button @click="load" :disabled="busy">{{busy?'正在更新…':'刷新故障记录'}}</button>
          <span v-if="summary" class="day3-target" :title="summary.probe_url">目标：{{summary.probe_url}}</span>
        </div>
        <p v-if="error" class="day3-error" role="alert">{{error}}</p>
        <p v-if="!monitoringOk" class="day3-unknown" role="status">监控状态：{{asText(monitored?.status)}}。缺少最新探测时，不能把节点标记为正常或故障；请检查采集服务与监控节点。</p>
        <div class="day3-cards">
          <div><small>已确认故障事件</small><strong>{{summary?.confirmed_incidents ?? '—'}}</strong><span>所选窗口</span></div>
          <div><small>当前故障节点</small><strong class="warn">{{summary?.active_nodes ?? '—'}}</strong><span>3 次失败后确认</span></div>
          <div><small>待确认 / 未知节点</small><strong>{{statuses.suspect + statuses.unknown}}</strong><span>未直接算作不可用</span></div>
          <div><small>MTTR · 平均故障恢复时长</small><strong>{{humanDuration(summary?.mttr_seconds)}}</strong><span>只统计已确认且恢复事件</span></div>
          <div><small>MTBF · 两次故障间正常时长</small><strong>{{humanDuration(summary?.mtbf_seconds)}}</strong><span>样本不足时不显示</span></div>
        </div>
        <div class="day3-block"><div class="day3-heading"><h3>节点当前状态</h3><small>每个目标独立计算；过期探测显示“未知”</small></div>
          <div class="day3-scroll"><table><thead><tr><th>节点</th><th>状态</th><th>连续失败</th><th>恢复确认</th><th>最近探测</th><th>窗口内事件</th></tr></thead><tbody>
          <tr v-for="node in nodes" :key="node.provider+'|'+node.name">
            <td><strong>{{node.name}}</strong><small>{{node.provider}} · {{node.kind}}</small></td>
            <td><span class="day3-chip" :class="node.status">{{asText(node.status)}}</span></td>
            <td>{{node.status==='unknown'?'—':node.failure_streak}}</td><td>{{node.status==='unknown'?'—':node.success_streak+' / 2'}}</td>
            <td>{{timeText(node.last_checked_at)}}</td><td>{{node.incidents}}</td>
          </tr><tr v-if="!nodes.length"><td colspan="6">等待第一轮新的 Day 3 探测数据</td></tr>
          </tbody></table></div></div>
        <div class="day3-block"><div class="day3-heading"><h3>故障事件时间线</h3><label>筛选节点 <select v-model="selectedNode"><option value="all">全部节点</option><option v-for="n in nodes" :key="n.provider+n.name" :value="JSON.stringify([n.provider,n.name])">{{n.name}}</option></select></label></div>
          <p v-if="!displayedEvents.length" class="day3-empty">当前统计窗口暂无已确认故障。这只表示 Day 3 开始记录以来尚无事件，不代表历史从未发生故障。</p>
          <div v-for="ev in displayedEvents" :key="ev.id" class="day3-event">
            <div class="day3-event-top"><strong>{{ev.name}}</strong><span :class="['day3-chip',ev.status]">{{ev.status==='resolved'?'已恢复':ev.status==='interrupted'?'监控中断':'未确认恢复'}}</span></div>
            <div class="day3-timeline"><span :style="incidentBar(ev)" :class="ev.status"></span></div>
            <div class="day3-event-detail"><span>首次失败 {{timeText(ev.started_at)}}</span><span>故障确认 {{timeText(ev.confirmed_at)}}</span><span>结束 {{timeText(ev.ended_at)}}</span><span>时长 {{humanDuration(ev.duration_seconds)}}</span></div>
          </div>
        </div>
        <p class="day3-foot">Day 3 只记录安装后新产生的故障事件，不回填旧 SQLite 探测记录。事件时长从首次失败至第二次恢复成功；“监控中断”不等于节点恢复。探测成功率与合同 SLA 不同。</p>
      </section>
    </main>
  `
}
