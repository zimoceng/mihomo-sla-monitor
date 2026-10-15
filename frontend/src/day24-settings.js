import { computed, onMounted, ref } from 'vue'
import './day24.css'

const PRESETS = [
  { label: 'Google 204', url: 'https://www.google.com/generate_204' },
  { label: 'Gstatic 204', url: 'https://www.gstatic.com/generate_204' },
  { label: 'GitHub HTTPS', url: 'https://github.com' }
]

export default {
  setup() {
    const url = ref('')
    const interval = ref(60)
    const timeout = ref(5000)
    const preset = ref('custom')
    const loading = ref(false)
    const saving = ref(false)
    const error = ref('')
    const success = ref('')
    const stored = ref(null)
    const isDirty = computed(() => stored.value && (
      url.value !== stored.value.probe_url ||
      Number(interval.value) !== stored.value.interval_seconds ||
      Number(timeout.value) !== stored.value.timeout_ms
    ))

    async function getConfig() {
      loading.value = true; error.value = ''; success.value = ''
      try {
        const response = await fetch('/api/settings/probe', { cache: 'no-store' })
        if (!response.ok) throw new Error(`获取配置失败：HTTP ${response.status}`)
        const value = await response.json()
        url.value = value.probe_url
        interval.value = value.interval_seconds
        timeout.value = value.timeout_ms
        stored.value = value
        preset.value = PRESETS.find(x => x.url === url.value)?.url || 'custom'
      } catch (e) { error.value = e.message }
      finally { loading.value = false }
    }
    function choosePreset(e) {
      preset.value = e.target.value
      if (preset.value !== 'custom') url.value = preset.value
    }
    function inputUrl(e) {
      url.value = e.target.value
      preset.value = PRESETS.find(x => x.url === url.value)?.url || 'custom'
    }
    async function save() {
      if (saving.value) return
      saving.value = true; error.value = ''; success.value = ''
      try {
        const response = await fetch('/api/settings/probe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            probe_url: url.value,
            interval_seconds: Number(interval.value),
            timeout_ms: Number(timeout.value)
          })
        })
        const result = await response.json().catch(() => ({}))
        if (!response.ok) {
          const detail = typeof result.detail === 'string' ? result.detail : `HTTP ${response.status}`
          throw new Error(detail)
        }
        stored.value = result
        success.value = result.message || '已保存，下一轮生效'
        // Dashboard's target selector will show the new URL once probe data is collected.
      } catch (e) { error.value = `保存失败：${e.message}` }
      finally { saving.value = false }
    }
    const savedTime = computed(() => {
      if (!stored.value?.saved_at) return '尚未通过网页保存（使用启动默认配置）'
      const date = new Date(stored.value.saved_at)
      return Number.isNaN(date.getTime()) ? '已保存' : date.toLocaleString('zh-CN')
    })

    onMounted(getConfig)
    return { PRESETS, preset, url, interval, timeout, loading, saving, error, success, stored, isDirty, savedTime, choosePreset, inputUrl, getConfig, save }
  },
  template: `
    <main class="day24-page">
      <section class="day24-panel">
        <header class="day24-header">
          <div>
            <div class="day24-eyebrow">NETWORK OBSERVABILITY / DAY 2.4</div>
            <h2>探测配置中心</h2>
            <p>直接从网页调整探测目标、频率和超时；无需手动修改 app.py。</p>
          </div>
          <span class="day24-saved" :class="{'day24-dirty': isDirty}">{{ isDirty ? '有未保存的修改' : '配置已同步' }}</span>
        </header>
        <div class="day24-form">
          <label class="day24-field day24-full">常用检测目标
            <select :value="preset" @change="choosePreset" :disabled="loading || saving">
              <option v-for="item in PRESETS" :key="item.url" :value="item.url">{{ item.label }}</option>
              <option value="custom">自定义 HTTPS URL</option>
            </select>
          </label>
          <label class="day24-field day24-full">实际探测 URL
            <input :value="url" @input="inputUrl" type="url" placeholder="https://example.com/health" spellcheck="false" autocomplete="off" :disabled="loading || saving" maxlength="500" />
          </label>
          <label class="day24-field">检测间隔（秒）
            <input v-model.number="interval" type="number" min="30" max="3600" step="1" :disabled="loading || saving" />
            <small>30–3600 秒，默认 60 秒</small>
          </label>
          <label class="day24-field">单节点超时（毫秒）
            <input v-model.number="timeout" type="number" min="1000" max="30000" step="500" :disabled="loading || saving" />
            <small>1000–30000 ms，默认 5000 ms</small>
          </label>
        </div>
        <div class="day24-actions">
          <button class="day24-save" type="button" @click="save" :disabled="loading || saving || !isDirty">{{ saving ? '正在保存…' : '保存探测设置' }}</button>
          <button class="day24-reload" type="button" @click="getConfig" :disabled="loading || saving">重新读取</button>
          <span class="day24-meta">上次保存：{{ savedTime }}</span>
        </div>
        <p v-if="success" class="day24-success" role="status">{{ success }}</p>
        <p v-if="error" class="day24-error" role="alert">{{ error }}</p>
        <p class="day24-note">新参数将在下一轮采集生效；历史探测记录保留，Day 2.3 按探测 URL 独立分析。自定义地址仅支持公共 HTTPS 域名及默认 443 端口。当前版本未启用登录认证，请将面板限定在可信局域网或 SSH 隧道内。</p>
      </section>
    </main>
  `
}
