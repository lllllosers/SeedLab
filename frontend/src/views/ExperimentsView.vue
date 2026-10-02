<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Experiment, ExperimentStatus } from '../types'
import { dateText, statusLabels } from '../utils'
import { Plus, Search } from '@element-plus/icons-vue'
import { useClientPagination } from '../composables/useClientPagination'

const router = useRouter(),
  route = useRoute(),
  items = ref<Experiment[]>([]),
  query = ref(''),
  status = ref(typeof route.query.status === 'string' ? route.query.status : ''),
  loading = ref(false)
const sort = ref<{ prop: string; order: string | null }>({
  prop: 'created_at',
  order: 'descending',
})
function onSortChange(value: { prop: string; order: string | null }) {
  sort.value = { prop: value.prop || 'created_at', order: value.order }
  resetPage()
}
const visibleItems = computed(() =>
  [...items.value].sort((a, b) => {
    const prop = sort.value.prop as keyof Experiment
    const direction = sort.value.order === 'ascending' ? 1 : -1
    return direction * String(a[prop] || '').localeCompare(String(b[prop] || ''))
  }),
)
const { page, pageSize, pageItems, resetPage } = useClientPagination(visibleItems)
watch(
  () => route.query.status,
  (value) => {
    status.value = typeof value === 'string' ? value : ''
    load()
  },
)
function changeStatusFilter() {
  resetPage()
  router.replace({ query: { ...route.query, status: status.value || undefined } })
}
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
      <div class="eyebrow">实验管理</div>
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
          @input="
            () => {
              resetPage()
              load()
            }
          "
        />
      </div>
    </div>
    <el-tabs v-model="status" class="experiment-status-tabs" @tab-change="changeStatusFilter"
      ><el-tab-pane label="全部" name="" /><el-tab-pane label="草稿" name="draft" /><el-tab-pane
        label="已就绪"
        name="ready" /><el-tab-pane label="进行中" name="active" /><el-tab-pane
        label="已完成"
        name="completed" /><el-tab-pane label="已终止" name="cancelled"
    /></el-tabs>
    <el-table
      :data="pageItems"
      v-loading="loading"
      class="data-table"
      @sort-change="onSortChange"
      empty-text="暂无实验，点击右上角创建"
      ><el-table-column
        prop="code"
        label="实验编号"
        width="195"
        sortable="custom"
      /><el-table-column
        prop="experiment_type_label"
        label="实验类型"
        width="150"
      /><el-table-column prop="name" sortable="custom" label="实验名称" min-width="300"
        ><template #default="{ row }"
          ><router-link class="table-link strong" :to="`/experiments/${row.id}`">{{
            row.name
          }}</router-link>
          <div class="table-subtitle">{{ row.description || '暂无说明' }}</div></template
        ></el-table-column
      ><el-table-column label="状态" prop="status" width="120" sortable="custom"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.status">{{
            statusLabels[row.status as ExperimentStatus]
          }}</span></template
        ></el-table-column
      ><el-table-column prop="planned_start_date" label="计划日期" width="140" sortable="custom"
        ><template #default="{ row }">{{
          dateText(row.planned_start_date)
        }}</template></el-table-column
      >
      <el-table-column label="创建日期" prop="created_at" width="140" sortable="custom"
        ><template #default="{ row }">{{ dateText(row.created_at) }}</template></el-table-column
      ><el-table-column label="操作" width="140"
        ><template #default="{ row }"
          ><el-button
            link
            type="primary"
            @click="
              router.push(
                row.status === 'active'
                  ? `/experiments/${row.id}/germination`
                  : `/experiments/${row.id}`,
              )
            "
            >{{
              row.status === 'draft'
                ? '继续配置'
                : row.status === 'ready'
                  ? '准备开始'
                  : row.status === 'active'
                    ? '进入实验'
                    : '查看详情'
            }}</el-button
          ></template
        ></el-table-column
      ></el-table
    >
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      class="list-pagination"
      :page-sizes="[25, 50, 100]"
      layout="total, sizes, prev, pager, next"
      :total="visibleItems.length"
    />
  </div>
</template>
