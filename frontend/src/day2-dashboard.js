import { computed, onMounted, onUnmounted, ref } from 'vue'
import './day2.css'

const Dashboard = {
  setup() {

    const hours = ref(24)
    const targets = ref([])
    const selectedUrl = ref('')
    const analyticsNodes = ref([])
    const summary = ref(null)
    const selectedKeys = ref([])
    const historyByNode = ref({})
    const sortMode = ref('p95')
    const keyword = ref('')
    const busy = ref(false)
    const graphBusy = ref(false)
    const error = ref('')
    const lastUpdated = ref('')

    const COLORS = ['#72b8ff', '#68ddb6', '#f7bd75']
    const NODE_LIMIT = 3
    const GRAPH = { width: 940, height: 290, left: 60, right: 24, top: 18, bottom: 45 }
    let poller = null
    let dataVersion = 0
    let graphVersion = 0

    const nodeKey = node => JSON.stringify([node.provider, node.name])
    const fmtValue = (value, unit = '') => value === null || value === undefined ? '—' : `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 1 })}${unit}`
    const fmtTime = timestamp => {
      const d = new Date(timestamp)
      return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    }
    async function request(path) {
      const response = await fetch(path, { cache: 'no-store' })
      if (!response.ok) throw new Error(`${path.split('?')[0]} 返回 HTTP ${response.status}`)
      return await response.json()
    }
    const query = (path, args) => `${path}?${new URLSearchParams(args)}`

    const sortedNodes = computed(() => {
      const search = keyword.value.trim().toLowerCase()
      const filtered = analyticsNodes.value.filter(n => !search || `${n.name} ${n.provider} ${n.kind}`.toLowerCase().includes(search))
      return [...filtered].sort((a, b) => {
        if (sortMode.value === 'name') return a.name.localeCompare(b.name)
        if (sortMode.value === 'success') return (b.availability_pct ?? -1) - (a.availability_pct ?? -1)
        const aa = a.p95_ms ?? Number.POSITIVE_INFINITY
        const bb = b.p95_ms ?? Number.POSITIVE_INFINITY
        return aa - bb || a.name.localeCompare(b.name)
      })
    })
    const selectedNodes = computed(() => selectedKeys.value.map(k => analyticsNodes.value.find(n => nodeKey(n) === k)).filter(Boolean))
    const currentTarget = computed(() => selectedUrl.value || summary.value?.probe_url || '')
    const isSelected = node => selectedKeys.value.includes(nodeKey(node))
    const selectedTargetLabel = computed(() => {
      const t = currentTarget.value
      if (!t) return '尚无检测目标'
      if (t.includes('www.google.com/generate_204')) return 'Google 204'
      if (t.includes('www.gstatic.com/generate_204')) return 'Gstatic 204'
      return t
    })

    async function refreshAll() {
      const version = ++dataVersion
      graphVersion++
      busy.value = true
      error.value = ''
      try {
        const targetResponse = await request(query('/api/analytics/targets', { hours: hours.value }))
        if (version !== dataVersion) return
        targets.value = targetResponse.targets || []
        const allowed = new Set(targets.value.map(t => t.probe_url))
        if (!allowed.has(selectedUrl.value)) selectedUrl.value = targetResponse.selected_probe_url || targets.value[0]?.probe_url || ''
        const params = { hours: hours.value }
        if (selectedUrl.value) params.probe_url = selectedUrl.value
        const [nodeResponse, summaryResponse] = await Promise.all([
          request(query('/api/analytics/nodes', params)),
          request(query('/api/analytics/summary', params))
        ])
        if (version !== dataVersion) return
        analyticsNodes.value = Array.isArray(nodeResponse) ? nodeResponse : []
        summary.value = summaryResponse
        const validKeys = new Set(analyticsNodes.value.map(nodeKey))
        selectedKeys.value = selectedKeys.value.filter(k => validKeys.has(k)).slice(0, NODE_LIMIT)
        if (selectedKeys.value.length === 0) {
          const candidates = analyticsNodes.value.filter(n => n.samples > 0).sort((a, b) => (a.p95_ms ?? Infinity) - (b.p95_ms ?? Infinity))
          const ga = candidates.filter(n => /\bGA\b/i.test(n.name))
          selectedKeys.value = (ga.length ? ga : candidates).slice(0, 2).map(nodeKey)
        }
        lastUpdated.value = new Date().toLocaleTimeString('zh-CN')
        await loadHistories()
      } catch (e) {
        if (version === dataVersion) error.value = `分析数据加载失败：${e.message}`
      } finally {
        if (version === dataVersion) busy.value = false
      }
    }

    async function loadHistories() {
      const version = ++graphVersion
      graphBusy.value = true
      try {
        const params = { hours: hours.value }
        if (selectedUrl.value) params.probe_url = selectedUrl.value
        const pairs = await Promise.all(selectedNodes.value.map(async n => {
          const result = await request(query('/api/analytics/history', { ...params, provider: n.provider, name: n.name }))
          return [nodeKey(n), result]
        }))
        if (version !== graphVersion) return
        historyByNode.value = Object.fromEntries(pairs)
      } catch (e) {
        if (version === graphVersion) error.value = `历史曲线加载失败：${e.message}`
      } finally {
        if (version === graphVersion) graphBusy.value = false
      }
    }
    function toggleNode(node) {
      const key = nodeKey(node)
      if (selectedKeys.value.includes(key)) selectedKeys.value = selectedKeys.value.filter(x => x !== key)
      else if (selectedKeys.value.length < NODE_LIMIT) selectedKeys.value = [...selectedKeys.value, key]
      else { error.value = `最多同时选择 ${NODE_LIMIT} 个节点`; return }
      error.value = ''
      loadHistories()
    }

    const graph = computed(() => {
      const { width, height, left, right, top, bottom } = GRAPH
      const plotW = width - left - right
      const plotH = height - top - bottom
      const now = Date.now()
      const start = now - hours.value * 3600 * 1000
      const all = selectedKeys.value.flatMap(k => historyByNode.value[k]?.points || [])
      const latencies = all.filter(p => p.success && Number.isFinite(p.latency_ms)).map(p => p.latency_ms)
      const rawMax = latencies.length ? Math.max(...latencies) : 100
      const tickStep = rawMax <= 250 ? 50 : rawMax <= 1000 ? 200 : rawMax <= 3000 ? 500 : 1000
      const maxMs = Math.max(100, Math.ceil((rawMax * 1.08) / tickStep) * tickStep)
      const x = time => left + Math.min(1, Math.max(0, (Date.parse(time) - start) / (now - start))) * plotW
      const y = ms => top + plotH - Math.min(1, Math.max(0, ms / maxMs)) * plotH
      const maxGap = Math.max(3 * 60 * 1000, hours.value * 3600 * 1000 / 600 * 4)
      const series = selectedNodes.value.map((n, index) => {
        const points = historyByNode.value[nodeKey(n)]?.points || []
        const segments = []
        const failures = []
        let current = []
        let lastTime = null
        function flush() { if (current.length > 0) segments.push(current); current = [] }
        for (const p of points) {
          const stamp = Date.parse(p.time)
          if (!Number.isFinite(stamp) || stamp < start || stamp > now + 30000) continue
          if (!p.success || !Number.isFinite(p.latency_ms)) {
            flush()
            failures.push({ cx: x(p.time), cy: top + plotH - 3, title: `${n.name} · ${fmtTime(p.time)} · 探测失败` })
            lastTime = null
          } else {
            if (lastTime !== null && stamp - lastTime > maxGap) flush()
            current.push({ x: x(p.time), y: y(p.latency_ms), time: p.time, ms: p.latency_ms })
            lastTime = stamp
          }
        }
        flush()
        return {
          key: nodeKey(n), name: n.name, color: COLORS[index % COLORS.length],
          segments: segments.map(seg => seg.length === 1
            ? `M ${seg[0].x.toFixed(1)} ${seg[0].y.toFixed(1)} l 0.1 0`
            : seg.map((pt, idx) => `${idx === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`).join(' ')),
          failures
        }
      })
      return {
        series, hasData: all.length > 0,
        grids: Array.from({ length: 5 }, (_, i) => ({ value: Math.round(maxMs * i / 4), y: y(maxMs * i / 4) })),
        timeTicks: Array.from({ length: 5 }, (_, i) => {
          const t = new Date(start + (now - start) * i / 4).toISOString()
          return { x: x(t), label: fmtTime(t) }
        }),
        ...GRAPH, plotBottom: top + plotH, plotRight: left + plotW
      }
    })

    onMounted(() => {
      refreshAll()
      poller = setInterval(refreshAll, 60000)
    })
    onUnmounted(() => { if (poller) clearInterval(poller) })

    return { hours, targets, selectedUrl, analyticsNodes, summary, selectedKeys, historyByNode, sortMode, keyword, busy, graphBusy, error, lastUpdated, COLORS, fmtValue, fmtTime, sortedNodes, selectedNodes, currentTarget, isSelected, selectedTargetLabel, refreshAll, loadHistories, toggleNode, graph, nodeKey }
  },
  template: `  <main class="day2-page">
    <section class="day2-panel" aria-labelledby="day2-title">
      <div class="day2-topline">
        <div>
          <div class="day2-eyebrow">NETWORK OBSERVABILITY / DAY 2.3</div>
          <h2 id="day2-title">网络质量分析</h2>
          <p>按探测网址独立计算 · 延迟分位数 · 历史趋势 · 多节点对比</p>
        </div>
        <span class="day2-status">{{ busy ? '正在同步' : lastUpdated ? \`更新于 \${lastUpdated}\` : '等待数据' }}</span>
      </div>

      <div class="day2-controls">
        <label>检测目标
          <select v-model="selectedUrl" @change="refreshAll">
            <option v-if="!targets.length" value="">暂无历史检测目标</option>
            <option v-for="target in targets" :key="target.probe_url" :value="target.probe_url">
              {{ target.probe_url.includes('www.google.com/generate_204') ? 'Google 204' : target.probe_url.includes('www.gstatic.com/generate_204') ? 'Gstatic 204' : target.probe_url }} · {{ target.samples }} 次
            </option>
          </select>
        </label>
        <label>统计窗口
          <select v-model.number="hours" @change="refreshAll">
            <option :value="1">1 小时</option>
            <option :value="24">24 小时</option>
            <option :value="168">7 天</option>
            <option :value="720">30 天</option>
          </select>
        </label>
        <button type="button" class="day2-refresh" :disabled="busy" @click="refreshAll">{{ busy ? '加载中…' : '刷新分析' }}</button>
      </div>
      <p class="day2-target" :title="currentTarget">当前统计：{{ selectedTargetLabel }} <span>· {{ currentTarget || '无样本' }}</span></p>
      <p v-if="error" class="day2-alert" role="alert">{{ error }}</p>

      <div class="day2-kpis">
        <div class="day2-kpi"><span>探测成功率</span><strong>{{ fmtValue(summary?.availability_pct, '%') }}</strong><small>已完成探测，不计监控中断</small></div>
        <div class="day2-kpi"><span>有效样本数</span><strong>{{ fmtValue(summary?.samples) }}</strong><small>成功 {{ fmtValue(summary?.successes) }} · 失败 {{ fmtValue(summary?.failures) }}</small></div>
        <div class="day2-kpi"><span>有记录的节点</span><strong>{{ fmtValue(summary?.observed_nodes) }} / {{ fmtValue(summary?.nodes) }}</strong><small>当前订阅节点</small></div>
      </div>

      <div class="day2-subhead">
        <div><h3>节点质量明细</h3><p>勾选 1–3 个节点显示在下方的同一张趋势图中</p></div>
        <div class="day2-search">
          <input v-model="keyword" type="search" placeholder="搜索节点或协议" aria-label="搜索节点" />
          <select v-model="sortMode" aria-label="表格排序">
            <option value="p95">按 P95 从低到高</option>
            <option value="success">按成功率从高到低</option>
            <option value="name">按节点名称</option>
          </select>
        </div>
      </div>
      <div class="day2-table-wrap">
        <table class="day2-table">
          <thead><tr><th>对比</th><th>节点 / 协议</th><th>样本</th><th>成功率</th><th>平均</th><th>P50</th><th>P95</th><th>P99</th></tr></thead>
          <tbody>
            <tr v-for="node in sortedNodes" :key="nodeKey(node)" :class="{ 'day2-row-selected': isSelected(node) }">
              <td><input type="checkbox" :checked="isSelected(node)" :disabled="!isSelected(node) && selectedKeys.length >= 3" :aria-label="\`对比 \${node.name}\`" @change="toggleNode(node)" /></td>
              <td><strong>{{ node.name }}</strong><small>{{ node.kind }} · {{ node.provider }}</small></td>
              <td>{{ node.samples }}</td>
              <td :class="node.availability_pct !== null && node.availability_pct < 95 ? 'day2-warn' : 'day2-success'">{{ fmtValue(node.availability_pct, '%') }}</td>
              <td>{{ fmtValue(node.avg_ms, ' ms') }}</td>
              <td>{{ fmtValue(node.p50_ms, ' ms') }}</td>
              <td class="day2-p95">{{ fmtValue(node.p95_ms, ' ms') }}</td>
              <td>{{ fmtValue(node.p99_ms, ' ms') }} <span v-if="node.percentile_warning" class="day2-info" title="成功延迟样本不足 30，P95/P99 暂不稳定">数据不足</span></td>
            </tr>
            <tr v-if="!sortedNodes.length"><td colspan="8" class="day2-empty">该时间范围内没有匹配节点，或数据尚未加载。</td></tr>
          </tbody>
        </table>
      </div>

      <div class="day2-subhead day2-chart-head">
        <div><h3>历史延迟趋势</h3><p>与所选检测目标、时间窗口保持一致；红点代表抽样记录中的失败探测</p></div>
        <span class="day2-muted">{{ graphBusy ? '正在加载曲线…' : \`对比 \${selectedNodes.length} / 3 个节点\` }}</span>
      </div>
      <div class="day2-legend">
        <span v-for="(node, index) in selectedNodes" :key="nodeKey(node)"><i :style="{ background: COLORS[index] }"></i>{{ node.name }}</span>
        <span class="day2-failure-legend"><i></i>失败探测</span>
      </div>
      <div class="day2-chart">
        <svg v-if="graph.hasData" viewBox="0 0 940 290" role="img" aria-label="历史延迟趋势，按时间绘制毫秒值，失败标记为红色圆点">
          <g v-for="line in graph.grids" :key="\`y-\${line.value}\`">
            <line :x1="graph.left" :x2="graph.plotRight" :y1="line.y" :y2="line.y" class="day2-grid-line" />
            <text :x="graph.left - 9" :y="line.y + 4" text-anchor="end" class="day2-tick">{{ line.value }}</text>
          </g>
          <g v-for="(tick, index) in graph.timeTicks" :key="\`x-\${index}\`">
            <text :x="tick.x" :y="graph.height - 13" text-anchor="middle" class="day2-tick">{{ tick.label }}</text>
          </g>
          <g v-for="series in graph.series" :key="series.key">
            <path v-for="(segment, index) in series.segments" :key="index" :d="segment" fill="none" :stroke="series.color" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round" />
            <circle v-for="(fail, index) in series.failures" :key="\`f\${index}\`" :cx="fail.cx" :cy="fail.cy" r="4.5" fill="#f47f8d" stroke="#202b41" stroke-width="1.5"><title>{{ fail.title }}</title></circle>
          </g>
          <text x="7" y="14" class="day2-axis-label">ms</text>
        </svg>
        <div v-else class="day2-chart-empty">{{ selectedKeys.length ? '当前范围没有曲线数据；可切换检测目标或扩大统计窗口。' : '请先从上方表格中选择节点。' }}</div>
      </div>
      <p class="day2-footnote">P50/P95/P99 基于所选网址与时间窗口中的所有成功延迟样本计算；曲线每节点最多返回 600 个抽样点，因此故障标记可能不是全部失败记录。采集缺口不等于节点正常。切换检测网址只影响历史数据筛选，不会改变服务器的实时探测配置。</p>
    </section>
  </main>`
}

export default Dashboard
