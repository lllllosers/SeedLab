<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Experiment, ExperimentStatus } from '../types'
import { dateText, statusLabels } from '../utils'
import { Plus, Search } from '@element-plus/icons-vue'

const router = useRouter(),
  items = ref<Experiment[]>([]),
  query = ref(''),
  status = ref(''),
  loading = ref(false)
async function load() {
  loading.value = true
  try {
    items.value = (
      await api.get<Experiment[]>('/experiments', {
        params: { q: query.value, status: status.value || undefined },
      })
    ).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">EXPERIMENT MANAGEMENT</div>
      <h1>实验列表</h1>
      <p>设计可执行的实验方案，并在开始前核对材料与预计工作量。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="router.push('/experiments/new')"
      >创建实验</el-button
    >
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <div class="toolbar-title">
        <h3>实验档案</h3>
        <span>{{ items.length }} 项实验</span>
      </div>
      <div class="toolbar-actions">
        <el-input
          v-model="query"
          placeholder="搜索实验编号或名称"
          clearable
          :prefix-icon="Search"
          @input="load"
        /><el-select
          v-model="status"
          placeholder="全部状态"
          clearable
          style="width: 145px"
          @change="load"
          ><el-option label="草稿" value="draft" /><el-option
            label="已就绪"
            value="ready" /><el-option label="进行中" value="active" /><el-option
            label="已完成"
            value="completed" /><el-option label="已取消" value="cancelled"
        /></el-select>
      </div>
    </div>
    <el-table
      :data="items"
      v-loading="loading"
      class="data-table"
      empty-text="暂无实验，点击右上角创建"
      ><el-table-column prop="code" label="实验编号" width="170" /><el-table-column
        label="实验名称"
        min-width="300"
        ><template #default="{ row }"
          ><router-link class="table-link strong" :to="`/experiments/${row.id}`">{{
            row.name
          }}</router-link>
          <div class="table-subtitle">{{ row.description || '暂无说明' }}</div></template
        ></el-table-column
      ><el-table-column label="状态" width="120"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.status">{{
            statusLabels[row.status as ExperimentStatus]
          }}</span></template
        ></el-table-column
      ><el-table-column label="创建日期" width="140"
        ><template #default="{ row }">{{ dateText(row.created_at) }}</template></el-table-column
      ><el-table-column label="操作" width="100"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="router.push(`/experiments/${row.id}`)"
            >查看详情</el-button
          ></template
        ></el-table-column
      ></el-table
    >
  </div>
</template>
