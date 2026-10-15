import './console-theme.css'

// Sidebar switches between existing Vue apps without rebuilding or mutating them.
// If JS fails, all sections remain accessible as normal HTML content.
const nav = [...document.querySelectorAll('.console-nav a')]
const sections = [...document.querySelectorAll('.cf-section')]
const titles = {
  'sla-overview': '网络运行概览',
  'sla-analytics': '线路质量分析',
  'sla-incidents': '故障事件',
  'sla-coverage': '监控覆盖率',
  'sla-settings': '探测设置'
}
function showCurrentView() {
  const id = (location.hash || '#sla-overview').slice(1)
  const active = titles[id] ? id : 'sla-overview'
  sections.forEach(s => { s.hidden = s.id !== active })
  nav.forEach(link => {
    const yes = link.getAttribute('href') === '#' + active
    link.classList.toggle('active', yes)
    if (yes) link.setAttribute('aria-current','page')
    else link.removeAttribute('aria-current')
  })
  const heading = document.querySelector('.console-page-title h1')
  if (heading) heading.textContent = titles[active]
  window.scrollTo({top:0,behavior:'instant'})
}
window.addEventListener('hashchange',showCurrentView)
showCurrentView()

const label = document.getElementById('console-runtime-status')
const details = document.getElementById('console-runtime-details')
async function refresh() {
  try {
    const [health, meta] = await Promise.all([
      fetch('/api/incidents/health',{cache:'no-store'}),
      fetch('/api/meta',{cache:'no-store'})
    ])
    if (!health.ok || !meta.ok) throw new Error('API unavailable')
    const a = await health.json(), b = await meta.json()
    const good = a.status === 'healthy'
    label.textContent = good ? '监控运行正常' : '监控状态待检查'
    label.className = 'console-status ' + (good ? 'is-good' : 'is-warn')
    details.textContent = `${b.nodes ?? '—'} 个节点 · ${b.probes ?? '—'} 次历史探测`
  } catch {
    label.textContent = 'API 连接异常'
    label.className = 'console-status is-warn'
    details.textContent = '请检查后端与 SSH / 局域网访问'
  }
}
refresh()
setInterval(refresh, 60000)
