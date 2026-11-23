<template>
  <div>
    <div class="page-head">
      <div><h2 class="page-title">订单 {{ o.order_no || '' }}</h2>
        <div class="page-sub">状态 {{ o.status }} · {{ o.currency }} {{ Number(o.total || 0).toFixed(2) }} · 已收 {{ Number(o.received_amount || 0).toFixed(2) }}</div></div>
      <div class="toolbar">
        <el-button @click="$router.push('/orders')">返回列表</el-button>
        <el-button @click="dl(`/orders/${id}/pdf`, { filename: o.order_no })">导出 PI</el-button>
        <el-button type="primary" @click="payVisible = true">登记收款</el-button>
        <el-button type="primary" @click="shipVisible = true">新增出运批次</el-button>
      </div>
    </div>

    <div class="kpi-grid" style="margin-bottom: 12px">
      <div class="kpi"><div class="label">订单总额</div><div class="value">{{ Number(o.total || 0).toFixed(2) }}</div><div class="hint">{{ o.currency }}</div></div>
      <div class="kpi"><div class="label">已核销回款</div><div class="value">{{ Number(o.received_amount || 0).toFixed(2) }}</div><div class="hint">收款自动驱动状态</div></div>
      <div class="kpi"><div class="label">待收余额</div><div class="value">{{ (Number(o.total || 0) - Number(o.received_amount || 0)).toFixed(2) }}</div><div class="hint">{{ o.currency }}</div></div>
      <div class="kpi"><div class="label">交期</div><div class="value" style="font-size: 18px">{{ o.delivery_date || '-' }}</div><div class="hint">账期起算 {{ o.due_date || '-' }}</div></div>
    </div>

    <div class="card" style="margin-bottom: 12px">
      <div class="page-title" style="font-size: 14px; margin-bottom: 8px">订单明细（行快照，历史不受产品改名改价影响）</div>
      <div class="table-scroll sm">
        <el-table :data="o.items || []" size="small" border height="260">
          <el-table-column prop="line_no" label="#" min-width="50" />
          <el-table-column prop="oe_no" label="OE NO." min-width="150" />
          <el-table-column prop="name_snapshot" label="PRODUCT NAME" min-width="180" />
          <el-table-column prop="qty" label="数量" min-width="90" />
          <el-table-column prop="qty_shipped" label="已出运" min-width="90" />
          <el-table-column prop="unit_price" label="单价" min-width="110" />
          <el-table-column prop="amount" label="金额" min-width="120" />
        </el-table>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px">
      <div class="card">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">状态流转日志</div>
        <el-table :data="o.status_logs || []" size="small" class="table-scroll sm">
          <el-table-column prop="created_at" label="时间" min-width="150" />
          <el-table-column prop="from_status" label="原状态" min-width="130" />
          <el-table-column prop="to_status" label="新状态" min-width="140" />
          <el-table-column prop="trigger" label="驱动" min-width="90" />
        </el-table>
      </div>
      <div class="card">
        <div class="page-title" style="font-size: 14px; margin-bottom: 8px">分批出运（已出 {{ (o.shipments || []).length }} 批）</div>
        <el-table :data="o.shipments || []" size="small" class="table-scroll sm">
          <el-table-column prop="shipment_no" label="批次号" min-width="160" />
          <el-table-column prop="batch_seq" label="第N批" min-width="80" />
          <el-table-column prop="status" label="状态" min-width="120" />
          <el-table-column prop="total_ctn" label="箱数" min-width="80" />
          <el-table-column label="装箱单" min-width="90">
            <template #default="{ row }"><el-button link type="primary" size="small"
              @click="dl(`/shipments/${row.id}/pl`, { filename: row.shipment_no })">PL</el-button></template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="payVisible" title="登记收款并核销" width="480px">
      <el-form label-width="110px">
        <el-form-item label="金额"><el-input v-model.number="pay.amount" type="number" /></el-form-item>
        <el-form-item label="币种"><el-select v-model="pay.currency"><el-option v-for="x in ['USD','SAR','AED','CNY']" :key="x" :label="x" :value="x" /></el-select></el-form-item>
        <el-form-item label="结汇汇率"><el-input v-model.number="pay.exchange_rate" type="number" /></el-form-item>
        <el-form-item label="水单号"><el-input v-model="pay.water_bill_no" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="payVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPay">登记并核销到本单</el-button></template>
    </el-dialog>

    <el-dialog v-model="shipVisible" title="新增出运批次" width="520px">
      <el-form label-width="110px">
        <el-form-item label="本批出运数量"><el-input v-model.number="ship.qty" type="number" /></el-form-item>
        <el-form-item label="箱号"><el-input v-model="ship.ctn_no" /></el-form-item>
        <el-form-item label="ETD"><el-input v-model="ship.etd" placeholder="2026-12-01" /></el-form-item>
        <el-form-item label="提单号"><el-input v-model="ship.bl_no" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="shipVisible = false">取消</el-button>
        <el-button type="primary" @click="submitShip">创建批次</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { get, post, download as dl } from '../api'

const route = useRoute()
const id = route.params.id
const o = ref({})
const payVisible = ref(false)
const shipVisible = ref(false)
const pay = reactive({ amount: 0, currency: 'USD', exchange_rate: 1, water_bill_no: '' })
const ship = reactive({ qty: 0, ctn_no: '1', etd: '', bl_no: '' })

async function load() { o.value = await get(`/orders/${id}`) }
onMounted(load)

async function submitPay() {
  const p = await post('/payments', { direction: 'IN', method: 'TT', customer_id: o.value.customer_id,
    order_id: Number(id), ...pay })
  await post(`/payments/${p.id}/allocate`, { target_type: 'ORDER', target_id: Number(id), amount: pay.amount })
  ElMessage.success('收款已登记并核销，订单状态已自动推进')
  payVisible.value = false
  load()
}
async function submitShip() {
  const line = (o.value.items || [])[0]
  if (!line) return ElMessage.warning('订单没有明细')
  await post('/shipments', { order_id: Number(id), etd: ship.etd || null, bl_no: ship.bl_no,
    items: [{ order_item_id: line.id, product_id: line.product_id, name_snapshot: line.name_snapshot,
      oe_no: line.oe_no, qty: ship.qty, ctn_no: ship.ctn_no,
      amount: ship.qty * Number(line.unit_price || 0) }] })
  ElMessage.success('出运批次已创建')
  shipVisible.value = false
  load()
}
</script>
