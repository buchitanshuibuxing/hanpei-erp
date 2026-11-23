<template>
  <div>
    <div class="page-head"><div><h2 class="page-title">客户门户</h2>
      <div class="page-sub">只读隔离：客户仅可见自己的订单 / PI / 装箱单 / 对账余额</div></div>
      <el-button v-if="auth.scope !== 'portal'" @click="goLogin">用门户账号登录</el-button>
      <el-button v-else @click="load">刷新</el-button></div>
    <div v-if="auth.scope !== 'portal'" class="card">
      当前为内部账号。客户门户需要独立的 <b>scope=portal</b> 令牌，内部账号与门户令牌互不通用。
    </div>
    <template v-else>
      <div class="kpi-grid" style="margin-bottom: 12px">
        <div class="kpi"><div class="label">客户</div><div class="value" style="font-size: 18px">{{ profile.name }}</div><div class="hint">{{ profile.code }} · {{ profile.country }}</div></div>
        <div class="kpi"><div class="label">订单数</div><div class="value">{{ orders.length }}</div><div class="hint">{{ profile.currency }}</div></div>
        <div class="kpi"><div class="label">对账余额</div><div class="value">{{ Number(statement.balance_total || 0).toFixed(2) }}</div><div class="hint">订单总额 − 已收款</div></div>
      </div>
      <div class="card" style="margin-bottom: 12px">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">我的订单</div>
        <div class="table-scroll"><el-table :data="orders" size="small" border height="300">
          <el-table-column prop="order_no" label="订单号" width="170" />
          <el-table-column prop="status" label="状态" width="150" />
          <el-table-column prop="total" label="总额" width="130" />
          <el-table-column prop="received" label="已付" width="130" />
          <el-table-column prop="balance" label="余额" width="130" />
          <el-table-column prop="delivery_date" label="交期" width="130" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }"><el-button link type="primary" size="small" @click="confirm(row)">确认订单</el-button></template>
          </el-table-column></el-table></div>
      </div>
      <div class="card">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">我的单证</div>
        <el-table :data="docs" size="small" class="table-scroll sm">
          <el-table-column prop="doc_type" label="类型" width="110" /><el-table-column prop="doc_no" label="单证号" width="180" />
          <el-table-column prop="status" label="状态" width="110" /><el-table-column prop="generated_at" label="生成时间" width="180" />
        </el-table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { get, post } from '../api'
import { useAuth } from '../stores/auth'

const auth = useAuth()
const router = useRouter()
const profile = ref({})
const orders = ref([])
const docs = ref([])
const statement = ref({ rows: [], balance_total: 0 })

function goLogin() { auth.clear(); router.push('/login') }
async function load() {
  try {
    profile.value = await get('/portal/profile')
    orders.value = await get('/portal/orders')
    docs.value = await get('/portal/documents')
    statement.value = await get('/portal/statement')
  } catch { /* 拦截器已提示 */ }
}
async function confirm(row) {
  const res = await post(`/portal/orders/${row.id}/confirm`, {})
  ElMessage.success(res.message || '已确认')
}
onMounted(() => { if (auth.scope === 'portal') load() })
</script>
