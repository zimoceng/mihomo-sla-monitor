import { createApp } from 'vue'
import ProbeSettings from './day24-settings.js'

const element = document.getElementById('day24-app')
if (element) createApp(ProbeSettings).mount(element)
