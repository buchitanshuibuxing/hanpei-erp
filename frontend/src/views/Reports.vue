<template>
  <div>
    <div class="page-head"><div><h2 class="page-title">报表看板</h2>
      <div class="page-sub">口径：近 30 天滚动；利润口径 = 净利（含运费/佣金/汇差/退税）</div></div>
      <el-button @click="load">刷新</el-button></div>
    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="销售趋势" name="sales"><div ref="chartEl" class="card" style="height: 340px"></div></el-tab-pane>
      <el-tab-pane label="产品分析" name="product">
        <div class="card table-scroll"><el-table :data="productRows" size="small" border height="420">
          <el-table-column prop="code" label="编码" min-width="120" /><el-table-column prop="name" label="品名" min-width="180" />
          <el-table-column prop="qty" label="销量" min-width="110" /><el-table-column prop="amount" label="销售额" min-width="140" />
          <el-table-column prop="orders" label="订单行数" min-width="110" /></el-table></div>
      </el-tab-pane>
      <el-tab-pane label="渠道分析" name="channel">
        <div class="card table-scroll"><el-table :data="channelRows" size="small" border height="420">
          <el-table-column prop="channel" label="渠道" min-width="150" /><el-table-column prop="leads" label="线索" min-width="100" />
          <el-table-column prop="customers" label="客户" min-width="100" /><el-table-column prop="orders" label="订单" min-width="100" />
          <el-table-column prop="amount" label="销售额" min-width="140" /></el-table></div>
      </el-tab-pane>
      <el-tab-pane label="利润明细" name="profit">
        <div class="card table-scroll"><el-table :data="profitRows" size="small" border height="420">
          <el-table-column prop="order_no" label="订单号" min-width="170" /><el-table-column prop="revenue" label="收入" min-width="130" />
          <el-table-column prop="purchase_cost" label="采购成本" min-width="130" /><el-table-column prop="freight_share" label="运费" min-width="110" />
          <el-table-column prop="commission_fee" label="佣金" min-width="110" /><el-table-column prop="exchange_gain" label="汇差" min-width="110" />
          <el-table-column prop="net_profit" label="净利" min-width="130" /><el-table-column prop="margin_pct" label="毛利率%" min-width="110" /></el-table></div>
      </el-tab-pane>
      <el-tab-pane label="应收账龄" name="aging">
        <div class="kpi-grid" style="margin-bottom: 10px">
          <div class="kpi" v-for="(v,k) in aging.buckets || {}" :key="k"><div class="label">{{ AGING[k] || k }}</div>
            <div class="value">{{ Number(v).toLocaleString('zh-CN', {maximumFractionDigits:2}) }}</div></div>
        </div>
        <div class="card table-scroll"><el-table :data="aging.rows || []" size="small" border height="300">
          <el-table-column prop="order_no" label="订单号" min-width="170" /><el-table-column prop="customer" label="客户" min-width="180" />
          <el-table-column prop="remain" label="未收" min-width="130" /><el-table-column prop="due_date" label="起算日" min-width="130" />
          <el-table-column prop="days" label="账龄(天)" min-width="110" /><el-table-column prop="bucket" label="分档" min-width="110" /></el-table></div>
      </el-tab-pane>
      <el-tab-pane label="库存健康" name="inventory">
        <div class="card table-scroll"><el-table :data="invRows" size="small" border height="420">
          <el-table-column prop="code" label="编码" min-width="120" /><el-table-column prop="name" label="品名" min-width="180" />
          <el-table-column prop="qty" label="库存" min-width="110" /><el-table-column prop="available" label="可用" min-width="110" />
          <el-table-column prop="low" label="低库存" min-width="100" /><el-table-column prop="idle_90d" label="90天呆滞" min-width="110" /></el-table></div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { get } from '../api'

const tab = ref('sales')
const chartEl = ref(null)
const sales = ref([])
const productRows = ref([])
const channelRows = ref([])
const profitRows = ref([])
const invRows = ref([])
const aging = ref({ buckets: {}, rows: [] })
let chart = null
const AGING = { current: '未到期', d30: '1-30 天', d60: '31-60 天', d90: '61-90 天', over90: '90 天以上' }

async function load() {
  try {
    if (tab.value === 'sales') {
      sales.value = await get('/reports/sales', { months: 12 })
      await nextTick(); draw()
    } else if (tab.value === 'product') productRows.value = await get('/reports/products')
    else if (tab.value === 'channel') channelRows.value = await get('/reports/channels')
    else if (tab.value === 'profit') profitRows.value = (await get('/reports/profit')).items || []
    else if (tab.value === 'aging') aging.value = await get('/receivables/aging')
    else if (tab.value === 'inventory') invRows.value = await get('/reports/inventory-health')
  } catch { /* 拦截器已提示 */ }
}
function draw() {
  if (!chartEl.value) return
  chart = chart || echarts.init(chartEl.value)
  chart.setOption({
    tooltip: { trigger: 'axis' }, legend: { data: ['销售额', '回款', '订单数'] },
    grid: { left: 60, right: 40, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: sales.value.map(x => x.month) },
    yAxis: [{ type: 'value' }, { type: 'value', name: '订单数' }],
    series: [
      { name: '销售额', type: 'bar', data: sales.value.map(x => x.amount), itemStyle: { color: '#1f4e79' } },
      { name: '回款', type: 'line', data: sales.value.map(x => x.received), itemStyle: { color: '#d85a30' } },
      { name: '订单数', type: 'line', yAxisIndex: 1, data: sales.value.map(x => x.orders), itemStyle: { color: '#639922' } },
    ],
  })
}
onMounted(load)
</script>
