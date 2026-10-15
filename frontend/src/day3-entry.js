import { createApp } from 'vue'
import IncidentsDashboard from './day3-incidents.js'

const target = document.getElementById('day3-app')
if (target) createApp(IncidentsDashboard).mount(target)
