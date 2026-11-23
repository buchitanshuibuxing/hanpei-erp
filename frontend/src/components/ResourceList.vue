<template>
  <div>
    <div class="page-head">
      <div>
        <h2 class="page-title">{{ cfg.title }}</h2>
        <div class="page-sub">{{ cfg.module }} · 共 {{ total }} 条 · 统一分页每页 10 条</div>
      </div>
      <div class="toolbar">
        <el-input v-if="cfg.search" v-model="keyword" placeholder="搜索关键字" clearable
          style="width: 210px" @keyup.enter="load(1)" />
        <el-button @click="load(1)">查询</el-button>
        <el-button v-if="cfg.form && auth.can(cfg.module, 'create')" type="primary" @click="openForm()">新增</el-button>
        <el-button v-if="cfg.createRoute" type="primary" @click="router.push(cfg.createRoute)">{{ cfg.createText || '新建' }}</el-button>
        <el-button v-if="cfg.templateUrl" @click="dl(cfg.templateUrl, cfg.title + '导入模板')">导入模板</el-button>
        <el-button v-if="cfg.importUrl" @click="pickFile">Excel 导入</el-button>
        <input ref="fileInput" type="file" accept=".xlsx,.xls" class="hidden" @change="onFile" />
        <el-button v-if="cfg.exportUrl && auth.can(cfg.module, 'export')" @click="dl(cfg.exportUrl, cfg.title)">导出 Excel</el-button>
        <el-button @click="load(page)">刷新</el-button>
      </div>
    </div>

    <div class="card">
      <div class="table-scroll">
        <el-table :data="rows" size="small" border stripe height="420" @row-dblclick="onDblClick">
          <el-table-column v-for="col in cfg.columns" :key="col.prop" :prop="col.prop"
            :label="col.label" :width="col.width" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag v-if="col.type === 'tag'" size="small"
                :type="tagType(row[col.prop])">{{ row[col.prop] ?? '-' }}</el-tag>
              <span v-else-if="col.type === 'money'">{{ money(row[col.prop]) }}</span>
              <span v-else>{{ row[col.prop] === null ? '***' : (row[col.prop] ?? '-') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" fixed="right" :width="actionWidth">
            <template #default="{ row }">
              <el-button v-if="cfg.form && auth.can(cfg.module, 'edit')" link type="primary"
                size="small" @click="openForm(row)">编辑</el-button>
              <el-button v-if="cfg.rowRoute" link type="primary" size="small"
                @click="router.push(cfg.rowRoute + '/' + row.id)">详情</el-button>
              <el-button v-for="a in (EXTRA[key] || [])" :key="a.label" link size="small"
                :type="a.danger ? 'danger' : 'primary'" @click="runExtra(a, row)">{{ a.label }}</el-button>
              <el-button v-if="cfg.form && auth.can(cfg.module, 'delete')" link type="danger"
                size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :total="total" :page="page" :size="size"
        @update:page="p => page = p" @update:size="s => size = s" @change="load" />
    </div>

    <el-dialog v-model="formVisible" :title="(editing ? '编辑 ' : '新增 ') + cfg.title" width="620px">
      <el-form label-width="130px">
        <el-form-item v-for="f in cfg.form" :key="f.prop" :label="f.label">
          <el-select v-if="f.type === 'select'" v-model="form[f.prop]" style="width: 100%">
            <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
          </el-select>
          <el-switch v-else-if="f.type === 'switch'" v-model="form[f.prop]" />
          <el-input v-else-if="f.type === 'textarea'" v-model="form[f.prop]" type="textarea" :rows="3" />
          <el-input v-else-if="f.type === 'number'" v-model="form[f.prop]" type="number" />
          <el-input v-else v-model="form[f.prop]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="saveForm">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="extraVisible" :title="extraTitle" width="480px">
      <el-form label-width="120px">
        <el-form-item v-for="f in extraFields" :key="f.prop" :label="f.label">
          <el-select v-if="f.options" v-model="extraForm[f.prop]" style="width: 100%">
            <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
          </el-select>
          <el-input v-else v-model="extraForm[f.prop]" :type="f.type || 'text'" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="extraVisible = false">取消</el-button>
        <el-button type="primary" @click="submitExtra">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RESOURCES } from '../menu'
import { get, post, put, del, download as dl } from '../api'
import http from '../api'
import { useAuth } from '../stores/auth'
import Pager from './Pager.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const key = computed(() => route.meta.resource)
const cfg = computed(() => RESOURCES[key.value] || RESOURCES.products)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const keyword = ref('')
const formVisible = ref(false)
const editing = ref(false)
const form = reactive({})
const fileInput = ref(null)
const extraVisible = ref(false)
const extraTitle = ref('')
const extraFields = ref([])
const extraForm = reactive({})
let pendingExtra = null

// 业务动作：单据级操作与二次确认（附录 D.3）
const EXTRA = {
  quotations: [
    { label: 'PDF', kind: 'download', path: r => `/quotations/${r.id}/pdf`, file: r => `${r.quote_no}.pdf` },
    { label: 'Excel', kind: 'download', path: r => `/quotations/${r.id}/excel`, file: r => `${r.quote_no}.xlsx` },
    { label: '发送打点', kind: 'prompt', title: '记录发送', path: r => `/quotations/${r.id}/send`,
      fields: [{ prop: 'channel', label: '渠道', options: ['EMAIL', 'WHATSAPP', 'MANUAL'] }] },
    { label: '转订单', kind: 'confirm', title: '确认转为销售订单？', danger: false,
      path: r => `/quotations/${r.id}/convert`, after: '已生成销售订单' },
  ],
  orders: [
    { label: 'PI', kind: 'download', path: r => `/orders/${r.id}/pdf`, file: r => `${r.order_no}_PI.pdf` },
    { label: '推进状态', kind: 'prompt', title: '推进订单状态', path: r => `/orders/${r.id}/status`,
      fields: [{ prop: 'status', label: '目标状态', options: ['PREPARING', 'PENDING_BALANCE', 'READY_SHIP', 'PARTIAL_SHIPPED', 'SHIPPED', 'COLLECTING', 'CLOSED'] }] },
  ],
  payments: [
    { label: '核销', kind: 'prompt', title: '收款核销', path: r => `/payments/${r.id}/allocate`,
      fields: [{ prop: 'target_id', label: '订单ID', type: 'number' }, { prop: 'amount', label: '核销金额', type: 'number' }],
      defaults: r => ({ target_type: 'ORDER', target_id: r.order_id || '', amount: r.remaining || r.amount }) },
  ],
  approvals: [
    { label: '批准', kind: 'confirm', title: '确认批准该申请？', path: r => `/approvals/${r.id}/decide`, body: { approve: true } },
    { label: '拒绝', kind: 'confirm', title: '确认拒绝该申请？', danger: true, path: r => `/approvals/${r.id}/decide`, body: { approve: false } },
  ],
  shipments: [
    { label: '装箱单', kind: 'download', path: r => `/shipments/${r.id}/pl`, file: r => `${r.shipment_no}_PL.pdf` },
    { label: '分箱', kind: 'prompt', title: '登记分箱明细', path: r => `/shipments/${r.id}/cartons`,
      fields: [{ prop: 'ctn_no', label: '箱号' }, { prop: 'length', label: '长(M)', type: 'number' },
        { prop: 'width', label: '宽(M)', type: 'number' }, { prop: 'height', label: '高(M)', type: 'number' },
        { prop: 'weight', label: '重量(KG)', type: 'number' }] },
  ],
  stocktakes: [
    { label: '确认盘点', kind: 'confirm', title: '确认后将自动生成盘盈/盘亏调账流水，不可撤销。继续？',
      danger: true, path: r => `/stocktakes/${r.id}/confirm` },
    { label: '导出盘点表', kind: 'download', path: r => `/stocktakes/${r.id}/export`, file: r => `${r.take_no}.xlsx` },
  ],
  'purchase-returns': [
    { label: '确认退货', kind: 'confirm', title: '确认后扣减库存并生成退款付款单进入审批流，不可撤销。继续？',
      danger: true, path: r => `/purchase-returns/${r.id}/confirm` },
  ],
  'purchase-orders': [
    { label: '到货入库', kind: 'prompt', title: '登记到货', path: r => `/purchase-orders/${r.id}/receive`,
      fields: [{ prop: 'item_id', label: '采购明细ID', type: 'number' }, { prop: 'qty', label: '到货数量', type: 'number' },
        { prop: 'quality_status', label: '质检', options: ['OK', 'CONCESSION', 'REJECT'] }] },
  ],
  leads: [
    { label: '转客户', kind: 'confirm', title: '确认把该线索转为正式客户？', path: r => `/leads/${r.id}/convert` },
  ],
  customers: [
    { label: '交接', kind: 'prompt', title: '客户交接', path: r => `/customers/${r.id}/transfer`,
      fields: [{ prop: 'new_owner', label: '新业务员' }] },
  ],
  claims: [
    { label: '处理', kind: 'prompt', title: '处理索赔', path: r => `/claims/${r.id}/resolve`,
      fields: [{ prop: 'resolution', label: '处理方式', options: ['REFUND', 'OFFSET', 'REPLACE', 'REJECT'] },
        { prop: 'responsibility', label: '责任方', options: ['SUPPLIER', 'LOGISTICS', 'INTERNAL', 'CUSTOMER'] }] },
  ],
  commissions: [
    { label: '标记发放', kind: 'confirm', title: '确认标记该笔提成已发放？', path: r => `/commissions/${r.id}/pay` },
  ],
  'customs-records': [
    { label: '转线索', kind: 'confirm', title: '确认把该条海关记录转为线索？', path: r => `/customs-records/${r.id}/to-lead` },
  ],
  'order-profits': [
    { label: '重算全部', kind: 'confirm', title: '按当前单据重算所有订单利润？', path: () => '/order-profits/recalculate' },
  ],
}

const actionWidth = computed(() => {
  const n = (EXTRA[key.value] || []).length + (cfg.value.form ? 2 : 0) + (cfg.value.rowRoute ? 1 : 0)
  return Math.max(120, Math.min(320, n * 62))
})

async function load(p = page.value) {
  page.value = p || 1
  try {
    const data = await get(cfg.value.endpoint, { page: page.value, size: size.value, keyword: keyword.value })
    rows.value = data.items || data || []
    total.value = data.total ?? rows.value.length
  } catch { rows.value = []; total.value = 0 }
}
watch(key, () => { keyword.value = ''; page.value = 1; load(1) }, { immediate: true })

function money(v) {
  if (v === null || v === undefined) return '***'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function tagType(v) {
  if (!v) return 'info'
  if (['ACTIVE', 'ISSUED', 'CONFIRMED', 'RECEIVED', 'APPROVED', 'CLOSED', 'OK', 'MATCHED'].includes(v)) return 'success'
  if (['PENDING', 'DRAFT', 'PENDING_APPROVAL', 'TODO', 'NEW'].includes(v)) return 'warning'
  if (['CANCELLED', 'REJECTED', 'BLACKLIST', 'LOW', 'REJECT'].includes(v)) return 'danger'
  return 'info'
}
function onDblClick(row) {
  if (cfg.value.rowRoute) router.push(cfg.value.rowRoute + '/' + row.id)
}

function openForm(row = null) {
  editing.value = !!row
  Object.keys(form).forEach(k => delete form[k])
  if (row) Object.assign(form, row)
  formVisible.value = true
}
async function saveForm() {
  try {
    if (editing.value) await put(`${cfg.value.endpoint}/${form.id}`, form)
    else await post(cfg.value.endpoint, form)
    ElMessage.success('已保存')
    formVisible.value = false
    load(page.value)
  } catch { /* 拦截器已提示 */ }
}
async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除 ${cfg.value.title} #${row.id}？此操作不可撤销。`, '删除确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await del(`${cfg.value.endpoint}/${row.id}`)
    ElMessage.success('已删除')
    load(page.value)
  } catch { /* 取消或错误 */ }
}
function pickFile() { fileInput.value?.click() }
async function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await http.post(cfg.value.importUrl, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    ElMessage.success(`导入完成：${JSON.stringify(res).slice(0, 120)}`)
    load(1)
  } catch { /* 拦截器已提示 */ }
  e.target.value = ''
}

async function runExtra(a, row) {
  const path = typeof a.path === 'function' ? a.path(row) : a.path
  if (a.kind === 'download') {
    try { await dl(path, { filename: typeof a.file === 'function' ? a.file(row) : a.file }) }
    catch { /* 拦截器已提示 */ }
    return
  }
  if (a.kind === 'confirm') {
    try {
      await ElMessageBox.confirm(a.title, '操作确认', { type: a.danger ? 'warning' : 'info' })
      const res = await post(path, a.body || {})
      ElMessage.success(a.after || res?.message || '操作成功')
      load(page.value)
    } catch { /* 取消或错误 */ }
    return
  }
  if (a.kind === 'prompt') {
    pendingExtra = { a, row, path }
    extraTitle.value = a.title
    extraFields.value = a.fields || []
    Object.keys(extraForm).forEach(k => delete extraForm[k])
    Object.assign(extraForm, a.defaults ? a.defaults(row) : {})
    extraVisible.value = true
  }
}
async function submitExtra() {
  if (!pendingExtra) return
  const body = { ...extraForm }
  Object.keys(body).forEach(k => {
    if (body[k] === '' || body[k] === null || body[k] === undefined) delete body[k]
    else if (typeof body[k] === 'string' && /^\d+(\.\d+)?$/.test(body[k]) && ['qty', 'amount', 'target_id', 'item_id', 'length', 'width', 'height', 'weight'].includes(k)) body[k] = Number(body[k])
  })
  try {
    const res = await post(pendingExtra.path, body)
    ElMessage.success(res?.message || '操作成功')
    extraVisible.value = false
    load(page.value)
  } catch { /* 拦截器已提示 */ }
}
</script>
