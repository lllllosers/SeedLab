<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Audit } from '../types'
import { actionLabels, dateText, entityLabels } from '../utils'

const items = ref<Audit[]>([])
onMounted(async () => {
  try {
    items.value = (await api.get<Audit[]>('/audit-logs')).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">SYSTEM / AUDIT TRAIL</div>
      <h1>操作记录</h1>
      <p>追踪重要数据的创建、修改、删除与导入。</p>
    </div>
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <div class="toolbar-title">
        <h3>最近操作</h3>
        <span>最多显示最近 100 条</span>
      </div>
    </div>
    <el-table :data="items" class="data-table" empty-text="暂无操作记录"
      ><el-table-column label="操作" width="130"
        ><template #default="{ row }"
          ><span class="action-badge">{{ actionLabels[row.action] || row.action }}</span></template
        ></el-table-column
      ><el-table-column label="数据类型" width="150"
        ><template #default="{ row }">{{
          entityLabels[row.entity_type] || row.entity_type
        }}</template></el-table-column
      ><el-table-column prop="entity_id" label="记录 ID" min-width="320" /><el-table-column
        label="时间"
        width="150"
        ><template #default="{ row }">{{ dateText(row.created_at) }}</template></el-table-column
      ></el-table
    >
  </div>
</template>
