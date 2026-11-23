<template>
  <div>
    <div class="page-head"><div><h2 class="page-title">系统参数与运维</h2>
      <div class="page-sub">敏感密钥加密存储，列表永不回显明文；修改实时生效到所有单据</div></div>
      <el-button type="primary" :loading="saving" @click="save">保存参数</el-button></div>
    <el-tabs v-model="tab">
      <el-tab-pane label="业务参数" name="settings">
        <div class="card table-scroll"><el-table :data="settings" size="small" border height="420">
          <el-table-column prop="key" label="参数键" min-width="260" />
          <el-table-column prop="description" label="说明" min-width="180" />
          <el-table-column label="值" min-width="260">
            <template #default="{ row }">
              <el-input v-model="row.value" size="small" :type="row.is_secret ? 'password' : 'text'"
                show-password :placeholder="row.is_secret ? '留空或 ****** 表示不修改' : ''" />
            </template>
          </el-table-column>
          <el-table-column prop="is_secret" label="敏感" min-width="90" /></el-table></div>
      </el-tab-pane>
      <el-tab-pane label="功能开关" name="flags">
        <div class="card table-scroll"><el-table :data="flags" size="small" border height="420">
          <el-table-column prop="code" label="开关" min-width="220" />
          <el-table-column prop="description" label="说明" min-width="240" />
          <el-table-column label="启用" min-width="110">
            <template #default="{ row }"><el-switch v-model="row.enabled" @change="toggle(row)" /></template>
          </el-table-column></el-table></div>
        <p class="muted" style="margin-top: 8px">采集/Agent/MCP/素材库/OCR/邮件实发默认关闭，按阶段开启（MVP 收敛交付面）。</p>
      </el-tab-pane>
      <el-tab-pane label="备份与恢复" name="backup">
        <div class="card">
          <el-button type="primary" @click="backup">立即备份数据库</el-button>
          <el-button @click="loadBackups">刷新列表</el-button>
          <el-table :data="backups" size="small" style="margin-top: 12px">
            <el-table-column prop="file" label="备份文件" /><el-table-column prop="size" label="大小(字节)" min-width="140" />
            <el-table-column prop="created_at" label="时间" min-width="200" /></el-table>
        </div>
      </el-tab-pane>
      <el-tab-pane label="权限矩阵" name="matrix">
        <div class="card table-scroll"><el-table :data="matrixRows" size="small" border height="420">
          <el-table-column prop="role" label="角色" min-width="150" />
          <el-table-column prop="module" label="模块" min-width="150" />
          <el-table-column prop="actions" label="允许动作" min-width="300" /></el-table></div>
        <p class="muted" style="margin-top: 8px">成本/毛利/底价字段按 cost 动作脱敏；业务员数据按 owner_name 隔离。</p>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { get, put, post } from '../api'

const tab = ref('settings')
const settings = ref([])
const flags = ref([])
const backups = ref([])
const matrixRows = ref([])
const saving = ref(false)

async function loadSettings() { settings.value = await get('/system/settings') }
async function loadFlags() { flags.value = await get('/system/feature-flags') }
async function loadBackups() { backups.value = await get('/system/backups') }
async function loadMatrix() {
  const m = await get('/auth/matrix')
  const rows = []
  Object.entries(m.matrix || {}).forEach(([role, mods]) => {
    Object.entries(mods).forEach(([module, actions]) => rows.push({ role, module, actions: actions.join(' / ') }))
  })
  matrixRows.value = rows
}
onMounted(() => { loadSettings(); loadFlags(); loadBackups(); loadMatrix() })

async function save() {
  saving.value = true
  try {
    const body = {}
    settings.value.forEach(s => { body[s.key] = s.value })
    await put('/system/settings', body)
    ElMessage.success('参数已保存，PDF 抬头等实时生效')
    loadSettings()
  } catch { /* 拦截器已提示 */ } finally { saving.value = false }
}
async function toggle(row) {
  await put(`/system/feature-flags/${row.code}`, { enabled: row.enabled })
  ElMessage.success(`${row.code} 已${row.enabled ? '开启' : '关闭'}`)
}
async function backup() {
  const res = await post('/system/backup', {})
  ElMessage.success(`备份完成：${res.file}`)
  loadBackups()
}
</script>
