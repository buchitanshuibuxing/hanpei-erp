<template>
  <div>
    <div class="page-head">
      <div><h2 class="page-title">{{ id ? '编辑报价 ' + head.quote_no : '新建报价单' }}</h2>
        <div class="page-sub">粘贴 OE 清单 → 自动匹配产品与客户协议价 → 生成 QT 版式报价单</div></div>
      <div class="toolbar">
        <el-button @click="$router.push('/quotations')">返回列表</el-button>
        <el-button v-if="id" @click="dl(`/quotations/${id}/pdf`, { filename: head.quote_no })">导出 PDF</el-button>
        <el-button v-if="id" @click="dl(`/quotations/${id}/excel`, { filename: head.quote_no })">导出 Excel</el-button>
        <el-button v-if="id" type="primary" @click="act(`/quotations/${id}/send`, { channel: 'EMAIL' })">发送打点</el-button>
        <el-button v-if="id" type="success" @click="convert">转销售订单</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存报价</el-button>
      </div>
    </div>

    <div class="card" style="margin-bottom: 12px">
      <el-form inline label-width="90px">
        <el-form-item label="客户">
          <el-select v-model="head.customer_id" filterable style="width: 260px" @change="loadCustomers">
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="币种">
          <el-select v-model="head.currency" style="width: 100px">
            <el-option v-for="c in ['USD', 'SAR', 'AED', 'CNY']" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="贸易条款"><el-input v-model="head.trade_terms" style="width: 100px" /></el-form-item>
        <el-form-item label="装运港"><el-input v-model="head.loading_port" style="width: 120px" /></el-form-item>
        <el-form-item label="目的地"><el-input v-model="head.destination" style="width: 120px" /></el-form-item>
        <el-form-item label="交期(天)"><el-input v-model.number="head.delivery_days" type="number" style="width: 100px" /></el-form-item>
        <el-form-item label="整单折扣%"><el-input v-model.number="head.discount_pct" type="number" style="width: 100px" /></el-form-item>
        <el-form-item label="页脚 Note"><el-input v-model="head.footer_note" style="width: 220px" /></el-form-item>
      </el-form>
    </div>

    <div class="card" style="margin-bottom: 12px">
      <div class="page-title" style="font-size: 14px; margin-bottom: 8px">询价单导入（粘贴 OE 号，支持换行/空格/逗号）</div>
      <el-input v-model="inquiry" type="textarea" :rows="3" placeholder="25100-03011 20&#10;17801-30030 10" />
      <div class="toolbar" style="margin-top: 8px">
        <el-button type="primary" @click="match">OE 匹配</el-button>
        <input ref="fileInput" type="file" accept=".xlsx,.xls" class="hidden" @change="onFile" />
        <el-button @click="fileInput?.click()">上传 Excel 询价清单</el-button>
        <el-button @click="items = []">清空明细</el-button>
        <span class="muted">匹配 {{ matchedCount }} / {{ items.length }} 行</span>
      </div>
      <div class="table-scroll">
        <el-table :data="items" size="small" border height="300">
          <el-table-column prop="line_no" label="#" min-width="50" />
          <el-table-column prop="oe_no" label="OE NO." min-width="150" />
          <el-table-column prop="name_snapshot" label="PRODUCT NAME" min-width="180" />
          <el-table-column prop="match_status" label="匹配" min-width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.match_status === 'MATCHED' ? 'success' : row.match_status === 'SUBSTITUTED' ? 'warning' : 'danger'">
                {{ row.match_status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="package_snapshot" label="PACKAGE" min-width="100" />
          <el-table-column label="QTY" min-width="110">
            <template #default="{ row }"><el-input v-model.number="row.qty" type="number" size="small" @change="recalc" /></template>
          </el-table-column>
          <el-table-column label="UNIT PRICE" min-width="130">
            <template #default="{ row }"><el-input v-model.number="row.unit_price" type="number" size="small" @change="recalc" /></template>
          </el-table-column>
          <el-table-column label="AMOUNT" min-width="120"><template #default="{ row }">{{ ((row.qty || 0) * (row.unit_price || 0)).toFixed(2) }}</template></el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ $index }"><el-button link type="danger" size="small" @click="items.splice($index, 1)">移除</el-button></template>
          </el-table-column>
        </el-table>
      </div>
      <div style="text-align: right; margin-top: 10px; font-size: 14px">
        小计 <b>{{ subtotal.toFixed(2) }}</b> · 折扣 <b>{{ discount.toFixed(2) }}</b> ·
        总计 <b style="color: var(--erp-blue); font-size: 17px">{{ total.toFixed(2) }} {{ head.currency }}</b>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { get, post, download as dl } from '../api'
import http from '../api'

const route = useRoute()
const router = useRouter()
const id = route.params.id || ''
const customers = ref([])
const items = ref([])
const inquiry = ref('')
const saving = ref(false)
const fileInput = ref(null)
const head = reactive({
  customer_id: 1, currency: 'USD', trade_terms: 'FOB', loading_port: 'Guangzhou',
  destination: 'Dubai', delivery_days: 45, discount_pct: 2, footer_note: '', quote_no: '',
})
const subtotal = computed(() => items.value.reduce((s, i) => s + (Number(i.qty) || 0) * (Number(i.unit_price) || 0), 0))
const discount = computed(() => subtotal.value * (Number(head.discount_pct) || 0) / 100)
const total = computed(() => subtotal.value - discount.value)
const matchedCount = computed(() => items.value.filter(i => i.match_status === 'MATCHED').length)

onMounted(async () => {
  await loadCustomers()
  if (id) {
    const q = await get(`/quotations/${id}`)
    Object.assign(head, q)
    items.value = (q.items || []).map(i => ({ ...i, qty: Number(i.qty), unit_price: Number(i.unit_price) }))
  }
})
async function loadCustomers() {
  const res = await get('/customers', { size: 100 })
  customers.value = res.items || []
}
function recalc() { /* computed 自动重算 */ }
async function match() {
  const res = await post('/inquiries/match', { text: inquiry.value, customer_id: head.customer_id, currency: head.currency })
  res.items.forEach((i, idx) => items.value.push({ ...i, line_no: items.value.length + 1, qty: i.qty || 1 }))
  ElMessage.success(`匹配完成：命中 ${res.matched} / ${res.total}`)
}
async function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const fd = new FormData(); fd.append('file', file)
  const res = await http.post('/inquiries/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  res.items.forEach(i => items.value.push({ ...i, line_no: items.value.length + 1 }))
  ElMessage.success(`已导入 ${res.total} 行`)
  e.target.value = ''
}
async function save() {
  if (!items.value.length) return ElMessage.warning('请先添加报价明细')
  saving.value = true
  try {
    const body = { ...head, items: items.value.map(i => ({
      product_id: i.product_id, oe_no: i.oe_no, name_snapshot: i.name_snapshot,
      package_snapshot: i.package_snapshot, unit: i.unit || 'PCS', qty: Number(i.qty) || 0,
      unit_price: Number(i.unit_price) || 0, match_status: i.match_status,
    })) }
    const res = id ? await http.put(`/quotations/${id}`, body) : await post('/quotations', body)
    ElMessage.success(id ? '已保存新版本' : `报价已创建：${res.quote_no}`)
    if (!id) router.push(`/quotations/edit/${res.id}`)
  } catch { /* 拦截器已提示 */ } finally { saving.value = false }
}
async function act(path, body) {
  try { const res = await post(path, body); ElMessage.success(res.message || '操作成功') }
  catch { /* 拦截器已提示 */ }
}
async function convert() {
  try {
    await ElMessageBox.confirm('确认把该报价转为销售订单？转单后报价不可再修改。', '转订单确认', { type: 'warning' })
    const res = await post(`/quotations/${id}/convert`, {})
    ElMessage.success(`已生成订单 ${res.order_no}`)
    router.push(`/orders/detail/${res.order_id}`)
  } catch { /* 取消 */ }
}
</script>
