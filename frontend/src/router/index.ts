import { createRouter, createWebHistory } from 'vue-router'

import IntervalClaimsView from '@/views/IntervalClaimsView.vue'
import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/interval-claims', name: 'interval-claims', component: IntervalClaimsView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
