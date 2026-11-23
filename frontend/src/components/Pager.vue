<template>
  <div class="pager">
    <span class="info">共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页 · 每页 {{ size }} 条</span>
    <el-button size="small" :disabled="page <= 1" @click="go(page - 1)">上一页</el-button>
    <span>第 <b>{{ page }}</b> / {{ pages }} 页</span>
    <el-button size="small" :disabled="page >= pages" @click="go(page + 1)">下一页</el-button>
    <el-select :model-value="size" size="small" style="width: 100px" @change="changeSize">
      <el-option v-for="n in [10, 15, 20, 50]" :key="n" :label="`${n} 条/页`" :value="n" />
    </el-select>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ total: Number, page: Number, size: Number })
const emit = defineEmits(['update:page', 'update:size', 'change'])
const pages = computed(() => Math.max(1, Math.ceil((props.total || 0) / (props.size || 10))))
function go(n) { emit('update:page', n); emit('change', n, props.size) }
function changeSize(n) { emit('update:size', n); emit('update:page', 1); emit('change', 1, n) }
</script>
