import { computed, ref, onMounted, onUnmounted } from 'vue'
import './day32.css'

const percentage = number => number == null ? '—' : `${Number(number).toFixed(2)}%`
const duration = seconds => {
  if (seconds == null) return '—'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${(seconds/60).toFixed(1)} 分钟`
  return `${(seconds/3600).toFixed(2)} 小时`
}
const stamp = value => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '—' : date.toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
}
const shortTarget = target => {
  if (!target) return '—'
  try { const u = new URL(target); return u.hostname.replace(/^www\./,'') + u.pathname } catch { return target }
}

export default {
  setup() {
    const hours = ref(24)
    const target = ref('')
    const targets = ref([])
    const summary = ref(null)
    const nodes = ref([])
    const selected = ref('')
    const timeline = ref(null)
    const error = ref('')
    const busy = ref(false)
    const lastUpdated = ref('')
    let poll = null
    let generation = 0
    const selectedNode = computed(() => nodes.value.find(n => JSON.stringify([n.provider,n.name]) === selected.value) || null)
    const worstFirst = computed(() => [...nodes.value].sort((a,b) => (a.coverage_pct ?? 0) - (b.coverage_pct ?? 0)))
    const incidentLabels = {open:'进行中',resolved:'已确认恢复',interrupted:'监控中断 / 未知'}
    const fetchData = async (path) => {
      const res = await fetch(path, {cache:'no-store'})
      if (!res.ok) throw new Error(`${path.split('?')[0]} HTTP ${res.status}`)
      return res.json()
    }
    async function loadTargets(){
      const result = await fetchData('/api/analytics/targets?hours=720')
      targets.value = Array.isArray(result.targets) ? result.targets : []
      if (!target.value) target.value = result.selected_probe_url || targets.value[0]?.probe_url || ''
    }
    async function load(){
      const seq=++generation
      busy.value=true
      error.value=''
      try {
        if (!target.value) await loadTargets()
        const params = new URLSearchParams({hours:String(hours.value)})
        if (target.value) params.set('probe_url',target.value)
        const [s,n] = await Promise.all([
          fetchData('/api/coverage/summary?'+params),
          fetchData('/api/coverage/nodes?'+params)
        ])
        if (seq!==generation) return
        summary.value=s
        nodes.value=n.nodes || []
        if (!selectedNode.value) {
          const first=nodes.value[0]
          selected.value=first ? JSON.stringify([first.provider,first.name]) : ''
        }
        if (selectedNode.value) {
          const detailParams = new URLSearchParams(params)
          detailParams.set('provider',selectedNode.value.provider)
          detailParams.set('name',selectedNode.value.name)
          detailParams.set('bins','48')
          const t=await fetchData('/api/coverage/timeline?'+detailParams)
          if (seq!==generation) return
          timeline.value=t
        } else timeline.value=null
        lastUpdated.value=new Date().toLocaleTimeString('zh-CN')
      } catch(e){ if (seq===generation) error.value='覆盖率分析获取失败：'+e.message }
      finally {if (seq===generation) busy.value=false}
    }
    async function chooseNode(node){
      selected.value=JSON.stringify([node.provider,node.name])
      await load()
    }
    const proportions = b => {
      const total=(b.healthy_seconds||0)+(b.down_seconds||0)+(b.unknown_seconds||0)
      return total<=0 ? {healthy:0,down:0,unknown:100} : {
        healthy:Math.min(100,100*b.healthy_seconds/total),
        down:Math.min(100,100*b.down_seconds/total),
        unknown:Math.min(100,100*b.unknown_seconds/total)
      }
    }
    onMounted(()=>{load();poll=setInterval(load,60000)})
    onUnmounted(()=>{clearInterval(poll); generation++})
    return {hours,target,targets,summary,nodes,worstFirst,selected,selectedNode,timeline,
      error,busy,lastUpdated,percentage,duration,stamp,shortTarget,proportions,incidentLabels,load,chooseNode}
  },
  template: `
    <main class="day32-root">
      <section class="day32-panel">
        <div class="day32-header">
          <div><div class="day32-eyebrow">NETWORK OBSERVABILITY / DAY 3.2</div>
            <h2>监控覆盖率与时间可用率</h2>
            <p>分开计算：实际有探测记录的时间、已确认故障时间、状态未知时间</p></div>
          <span class="day32-update">{{lastUpdated?'更新于 '+lastUpdated:'等待统计'}}</span>
        </div>
        <div class="day32-controls">
          <label>监测目标<select v-model="target" @change="load">
            <option v-for="t in targets" :key="t.probe_url" :value="t.probe_url">{{shortTarget(t.probe_url)}}</option>
          </select></label>
          <label>统计窗口<select v-model.number="hours" @change="load">
            <option :value="1">1 小时</option><option :value="24">24 小时</option>
            <option :value="168">7 天</option><option :value="720">30 天</option>
          </select></label>
          <button @click="load" :disabled="busy">{{busy?'计算中…':'刷新覆盖率'}}</button>
        </div>
        <p v-if="error" class="day32-error" role="alert">{{error}}</p>
        <div v-if="summary" class="day32-cards">
          <div><small>监控时间覆盖率</small><strong>{{percentage(summary.coverage_pct)}}</strong><span>有完成探测记录支持的时间</span></div>
          <div><small>已判定时间可用率</small><strong>{{percentage(summary.observed_availability_pct)}}</strong><span>正常 ÷ (正常 + 已确认故障)</span></div>
          <div><small>无采样时间</small><strong>{{duration(summary.unobserved_seconds)}}</strong><span>节点时间合计，不能视作故障</span></div>
          <div><small>有采样但状态未确定</small><strong>{{duration(summary.uncertain_seconds)}}</strong><span>疑似故障 / 恢复观察等</span></div>
        </div>
        <p v-if="summary" class="day32-note">统计范围内 {{summary.nodes}} 个节点。已判定时间可用率不包含未知时间，并非合同 SLA；若 Day 3.1 刚安装，之前的窗口部分会显示无采样。{{shortTarget(summary.probe_url)}}</p>
        <div class="day32-block">
          <h3>节点覆盖明细</h3>
          <div class="day32-scroll"><table><thead><tr><th>节点</th><th>覆盖率</th><th>已判定可用率</th><th>正常时长</th><th>确认故障时长</th><th>状态未知时长</th><th>查看</th></tr></thead><tbody>
            <tr v-for="n in worstFirst" :key="n.provider+'|'+n.name" :class="selected===JSON.stringify([n.provider,n.name])?'day32-active':''">
              <td><b>{{n.name}}</b><small>{{n.provider}}</small></td>
              <td>{{percentage(n.coverage_pct)}}</td><td>{{percentage(n.observed_availability_pct)}}</td>
              <td>{{duration(n.healthy_seconds)}}</td><td>{{duration(n.down_seconds)}}</td>
              <td>{{duration(n.unknown_seconds)}}</td>
              <td><button class="day32-select" @click="chooseNode(n)">查看时间线</button></td>
            </tr><tr v-if="!nodes.length"><td colspan="7">尚无节点数据</td></tr>
          </tbody></table></div>
        </div>
        <div class="day32-block" v-if="selectedNode && timeline">
          <div class="day32-heading"><h3>{{selectedNode.name}} · 时间状态分布</h3><span>绿色：正常 · 红色：已确认故障 · 灰色：未知</span></div>
          <div class="day32-bar-wrap" role="img" :aria-label="selectedNode.name+' 的监控时间状态分布'">
            <div v-for="(b,i) in timeline.buckets" :key="i" class="day32-bar" :title="stamp(b.start)+' ~ '+stamp(b.end)+'；正常 '+duration(b.healthy_seconds)+'；故障 '+duration(b.down_seconds)+'；未知 '+duration(b.unknown_seconds)">
              <span class="day32-green" :style="{height:proportions(b).healthy+'%'}"></span>
              <span class="day32-red" :style="{height:proportions(b).down+'%'}"></span>
              <span class="day32-gray" :style="{height:proportions(b).unknown+'%'}"></span>
            </div>
          </div>
          <div class="day32-axis"><span>{{stamp(timeline.window_start)}}</span><span>{{stamp(timeline.window_end)}}</span></div>
          <p class="day32-subtle">每根柱代表一个时间段；灰色既可能是监控缺口，也可能是探测已执行但尚不能判定故障。缺口不当作节点离线。</p>
          <h4>已确认故障事件</h4>
          <div v-if="!timeline.events.length" class="day32-empty">所选范围内没有已确认故障事件；并不表示所有时间都已受到有效监控。</div>
          <div v-for="event in timeline.events" :key="event.id" class="day32-event">
            <strong>{{incidentLabels[event.status] || event.status}}</strong>
            <span>首次失败：{{stamp(event.started_at)}}</span>
            <span>确认：{{stamp(event.confirmed_at)}}</span>
            <span>结束：{{stamp(event.ended_at)}}</span>
            <span>时长：{{duration(event.duration_seconds)}}</span>
          </div>
        </div>
        <p class="day32-footer">方法：只使用 Day 3.1 上线后有监控轮次关联的探测数据，每个样本最多代表当时一个探测周期。切换目标、采集失败或采集器停机期间属于未知。已确认故障是“指定 URL 的探测故障”，不一定等于节点服务器实际宕机。</p>
      </section>
    </main>
  `
}
