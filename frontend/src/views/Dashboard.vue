<template>
  <div>
    <div class="page-head">
      <div><h2 class="page-title">工作台</h2>
        <div class="page-sub">{{ data.scope || '近 30 天滚动' }} · 数据来自真实单据</div></div>
      <el-button @click="load">刷新</el-button>
    </div>
    <div class="kpi-grid">
      <div class="kpi" v-for="k in kpis" :key="k.label">
        <div class="label">{{ k.label }}</div>
        <div class="value">{{ k.value }}</div>
        <div class="hint">{{ k.hint }}</div>
      </div>
    </div>
    <div style="display: grid; grid-template-columns: 1.4fr 1fr; gap: 12px; margin-top: 12px">
      <div class="card">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">近 6 个月销售与回款（按原币）</div>
        <div ref="chartEl" style="height: 260px"></div>
      </div>
      <div class="card">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">订单状态分布</div>
        <el-table :data="statusRows" size="small" class="table-scroll sm">
          <el-table-column prop="status" label="状态" />
          <el-table-column prop="count" label="订单数" min-width="90" />
        </el-table>
      </div>
    </div>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px">
      <div class="card">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">低库存预警</div>
        <el-table :data="data.low_stock || []" size="small" class="table-scroll sm">
          <el-table-column prop="code" label="编码" min-width="110" />
          <el-table-column prop="name" label="品名" />
          <el-table-column prop="qty" label="库存" min-width="80" />
          <el-table-column prop="safety" label="安全线" min-width="80" />
        </el-table>
      </div>
      <div class="card">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">逾期未出运订单</div>
        <el-table :data="data.overdue_orders || []" size="small" class="table-scroll sm">
          <el-table-column prop="order_no" label="订单号" />
          <el-table-column prop="delivery_date" label="交期" />
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, nextTick } from 'vue'
import * as echarts from 'echarts'
import { get } from '../api'

const data = ref({ kpi: {} })
const sales = ref([])
const chartEl = ref(null)
let chart = null
const kpis = computed(() => {
  const k = data.value.kpi || {}
  return [
    { label: '近 30 天订单', value: k.order_count_30d ?? 0, hint: '按建单时间' },
    { label: '近 30 天销售额', value: Number(k.revenue_30d || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 }), hint: '按订单原币汇总' },
    { label: '近 30 天回款', value: Number(k.received_30d || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 }), hint: '按收款核销' },
    { label: '累计净利', value: Number(k.net_profit_all || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 }), hint: 'CNY · 口径 v1' },
    { label: '在办订单', value: k.open_orders ?? 0, hint: '未结案 / 未取消' },
    { label: '逾期订单', value: k.overdue_count ?? 0, hint: '交期已过' },
    { label: '低库存品种', value: k.low_stock_count ?? 0, hint: '低于安全库存' },
  ]
})
const statusRows = computed(() => Object.entries(data.value.status_breakdown || {}).map(([status, count]) => ({ status, count })))

async function load() {
  try {
    data.value = await get('/reports/dashboard')
    sales.value = await get('/reports/sales', { months: 6 })
    await nextTick()
    draw()
  } catch { /* 拦截器已提示 */ }
}
function draw() {
  if (!chartEl.value) return
  chart = chart || echarts.init(chartEl.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['销售额', '回款'] },
    grid: { left: 50, right: 20, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: sales.value.map(x => x.month) },
    yAxis: { type: 'value' },
    series: [
      { name: '销售额', type: 'bar', data: sales.value.map(x => x.amount), itemStyle: { color: '#1f4e79' } },
      { name: '回款', type: 'line', data: sales.value.map(x => x.received), itemStyle: { color: '#d85a30' } },
    ],
  })
}
onMounted(load)
</script>
