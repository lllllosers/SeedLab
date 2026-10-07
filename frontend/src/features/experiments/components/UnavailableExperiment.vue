<script setup lang="ts">
import PageBackButton from '../../../shared/components/PageBackButton.vue'
</script>
<template>
  <PageBackButton to="/experiments" label="返回实验列表" />
  <el-empty description="操作失败，请稍后重试" />
</template>
