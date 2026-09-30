<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Audit, Paged } from '../types'
import { actionLabels, dateTimeText, entityLabels } from '../utils'
import { auditDetails } from '../utils/audit'
const items = ref<Audit[]>([]),
  total = ref(0),
  page = ref(1),
  pageSize = ref(50),
  action = ref(''),
  entity = ref(''),
  search = ref(''),
  selected = ref<Audit | null>(null)
let sequence = 0
async function load() {
  const current = ++sequence
  try {
    const result = (
      await api.get<Paged<Audit>>('/audit-logs', {
        params: {
          page: page.value,
          page_size: pageSize.value,
          action: action.value || undefined,
          entity_type: entity.value || undefined,
          q: search.value || undefined,
        },
      })
    ).data
    if (current === sequence) {
      items.value = result.items
      total.value = result.total
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
watch([action, entity, search, pageSize], () => {
  if (page.value !== 1) page.value = 1
  else void load()
})
watch(page, () => void load())
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">操作记录</div>
      <h1>操作记录</h1>
      <p>查询操作者、具体实验对象和修改时间，查看修改前后的原始值。</p>
    </div>
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <el-input v-model="search" clearable placeholder="搜索实验编号、对象名称或操作者" /><el-select
        v-model="action"
        clearable
        placeholder="全部操作"
        ><el-option
          v-for="(label, key) in actionLabels"
          :key="key"
          :label="label"
          :value="key" /></el-select
      ><el-select v-model="entity" clearable placeholder="全部数据类型"
        ><el-option v-for="(label, key) in entityLabels" :key="key" :label="label" :value="key"
      /></el-select>
    </div>
    <el-table
      :data="items"
      empty-text="没有符合条件的操作记录，请调整筛选；新增或修改实验数据后可在这里查看。"
      ><el-table-column label="操作" width="90"
        ><template #default="{ row }">{{
          actionLabels[row.action] || '维护'
        }}</template></el-table-column
      ><el-table-column label="数据类型" prop="entity_label" width="130" /><el-table-column
        label="具体对象"
        prop="subject_label"
        min-width="280"
      /><el-table-column label="操作者" prop="user_display_name" width="140" /><el-table-column
        label="操作时间"
        width="185"
        ><template #default="{ row }">{{ dateTimeText(row.created_at) }}</template></el-table-column
      ><el-table-column label="操作" width="100"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="selected = row">查看详情</el-button></template
        ></el-table-column
      ></el-table
    >
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :page-sizes="[25, 50, 100]"
      :total="total"
      layout="total, sizes, prev, pager, next"
      class="list-pagination"
    />
  </div>
  <el-drawer :model-value="!!selected" title="操作详情" size="620px" @close="selected = null"
    ><template v-if="selected"
      ><h3>{{ selected.subject_label }}</h3>
      <p>{{ selected.user_display_name }} · {{ dateTimeText(selected.created_at) }}</p>
      <el-table
        :data="auditDetails(selected)"
        empty-text="本次操作已记录，可通过对象名称核对实验履历。"
        ><el-table-column prop="label" label="修改内容" width="160" /><el-table-column
          prop="before"
          label="修改前" /><el-table-column prop="after" label="修改后" /></el-table></template
  ></el-drawer>
</template>
