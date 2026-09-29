<script setup lang="ts">
import { ArrowLeft } from '@element-plus/icons-vue'

defineProps<{ to: string; label: string }>()
</script>

<template>
  <router-link class="page-back-button" :to="to">
    <el-icon><ArrowLeft /></el-icon><span>{{ label }}</span>
  </router-link>
</template>
