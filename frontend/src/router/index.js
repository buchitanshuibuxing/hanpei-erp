import { createRouter, createWebHashHistory } from 'vue-router'
import { RESOURCES } from '../menu'
import ResourceList from '../components/ResourceList.vue'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '工作台' } },
  { path: '/reports', component: () => import('../views/Reports.vue'), meta: { title: '报表看板' } },
  { path: '/settings', component: () => import('../views/Settings.vue'), meta: { title: '系统参数' } },
  { path: '/portal', component: () => import('../views/Portal.vue'), meta: { title: '客户门户' } },
  { path: '/quotations/new', component: () => import('../views/QuotationEdit.vue'), meta: { title: '新建报价' } },
  { path: '/quotations/edit/:id', component: () => import('../views/QuotationEdit.vue'), meta: { title: '编辑报价' } },
  { path: '/orders/detail/:id', component: () => import('../views/OrderDetail.vue'), meta: { title: '订单详情' } },
]

Object.keys(RESOURCES).forEach((key) => {
  routes.push({ path: '/' + key, component: ResourceList,
    meta: { title: RESOURCES[key].title, resource: key } })
})

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('erp_token')
  if (!to.meta.public && !token) return next('/login')
  if (to.path === '/login' && token) return next('/dashboard')
  next()
})

export default router
