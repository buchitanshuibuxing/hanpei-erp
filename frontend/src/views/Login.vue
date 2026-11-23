<template>
  <div class="login-wrap">
    <div class="login-card">
      <h1>Hanpei ERP</h1>
      <p>汽车配件外贸管理系统 · 产品 → 报价 → 订单 → 履约 → 利润</p>
      <el-tabs v-model="scope">
        <el-tab-pane label="内部账号" name="internal" />
        <el-tab-pane label="客户门户" name="portal" />
      </el-tabs>
      <el-form @keyup.enter="submit">
        <el-form-item><el-input v-model="form.username" placeholder="账号" size="large" /></el-form-item>
        <el-form-item><el-input v-model="form.password" placeholder="密码" type="password" size="large" show-password /></el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">登录</el-button>
      </el-form>
      <p class="muted" style="margin-top: 16px; font-size: 11px">
        初始账号：admin / admin123（内部） · alnoor / portal123（门户）<br />
        登录失败 5 次将锁定 15 分钟。
      </p>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../api'
import { useAuth } from '../stores/auth'

const router = useRouter()
const auth = useAuth()
const scope = ref('internal')
const loading = ref(false)
const form = reactive({ username: 'admin', password: 'admin123' })

async function submit() {
  loading.value = true
  try {
    const url = scope.value === 'portal' ? '/auth/portal/login' : '/auth/login'
    const data = await http.post(url, { username: form.username, password: form.password })
    auth.save(data)
    ElMessage.success('登录成功')
    router.push(scope.value === 'portal' ? '/portal' : '/dashboard')
  } catch (e) {
    // 统一拦截器已给出可读中文提示
  } finally { loading.value = false }
}
</script>
