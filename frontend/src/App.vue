<template>
  <div v-if="route.path === '/login'" style="height: 100%"><router-view /></div>
  <div v-else style="display: flex; flex-direction: column; height: 100%">
    <header class="topbar">
      <div class="brand">Hanpei ERP <small>汽车配件外贸管理系统 · v1.0</small></div>
      <div class="topbar-right">
        <el-button size="small" plain @click="searchVisible = true">全局搜索 Ctrl+K</el-button>
        <el-button size="small" plain @click="priceVisible = true">快速查价 F2</el-button>
        <span class="hide-mobile">{{ auth.user?.name }} · {{ auth.user?.role_name || auth.role }}</span>
        <el-button size="small" @click="logout">退出</el-button>
      </div>
    </header>
    <div style="display: flex; flex: 1; min-height: 0">
      <aside class="sidebar">
        <template v-for="g in MENUS" :key="g.group">
          <div class="group-title">{{ g.group }}</div>
          <router-link v-for="i in g.items" :key="i.path" :to="i.path"
            class="menu-item" :class="{ active: route.path === i.path }">
            <span>{{ i.title }}</span>
          </router-link>
        </template>
      </aside>
      <main class="main">
        <div class="content"><router-view /></div>
      </main>
    </div>

    <el-dialog v-model="searchVisible" title="全局搜索（客户 / 订单 / 报价 / OE 号）" width="620px">
      <el-input v-model="q" placeholder="输入 OE 号、单号或客户名" autofocus @input="doSearch" />
      <el-table :data="results" size="small" style="margin-top: 10px" @row-click="openResult">
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column prop="title" label="结果" />
      </el-table>
    </el-dialog>

    <el-dialog v-model="priceVisible" title="快速查价（F2）" width="480px">
      <el-input v-model="oe" placeholder="输入 OE 号，如 25100-03011" @keyup.enter="doPrice" />
      <el-button style="margin-top: 8px" type="primary" @click="doPrice">查询</el-button>
      <div v-if="price" class="card" style="margin-top: 12px">
        <p><b>{{ price.oe_no }}</b> {{ price.name }}</p>
        <p style="font-size: 18px; color: var(--erp-blue)">{{ price.currency }} {{ price.price?.toFixed(2) }}</p>
        <p class="muted">{{ price.snippet }}</p>
        <el-button size="small" @click="copy(price.snippet)">复制报价片段</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { MENUS } from './menu'
import { get } from './api'
import { useAuth } from './stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const searchVisible = ref(false)
const priceVisible = ref(false)
const q = ref('')
const results = ref([])
const oe = ref('')
const price = ref(null)

async function doSearch() {
  if (!q.value) { results.value = []; return }
  try { results.value = await get('/search', { q: q.value }) } catch { results.value = [] }
}
function openResult(row) { searchVisible.value = false; router.push(row.url) }
async function doPrice() {
  try { price.value = await get('/quick-price', { oe: oe.value, currency: 'USD' }) }
  catch { price.value = null }
}
function copy(text) {
  navigator.clipboard?.writeText(text)
  ElMessage.success('已复制到剪贴板')
}
function logout() { auth.clear(); router.push('/login') }
function onKey(e) {
  if (e.key === 'Escape') { searchVisible.value = false; priceVisible.value = false }
  if (e.ctrlKey && e.key.toLowerCase() === 'k') { e.preventDefault(); searchVisible.value = true }
  if (e.key === 'F2') { e.preventDefault(); priceVisible.value = true }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>
