<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import { Download, Files } from '@element-plus/icons-vue'
import IntegratedMaterialImport from './IntegratedMaterialImport.vue'
import type { Experiment } from '../types'
const experiments = ref<Experiment[]>([])
const selectedExperiments = ref<string[]>([])
const exporting = ref(false),
  ledgerBusy = ref(false)
onMounted(async () => {
  try {
    experiments.value = (await api.get<Experiment[]>('/experiments')).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})
function saveFile(data: Blob, filename: string) {
  const url = URL.createObjectURL(data),
    link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
async function exportExperiments() {
  if (!selectedExperiments.value.length) return ElMessage.warning('请至少选择一个实验')
  exporting.value = true
  try {
    const { data } = await api.post<Blob>(
      '/export/experiments/workbook.xlsx',
      { experiment_ids: selectedExperiments.value },
      { responseType: 'blob' },
    )
    saveFile(data, 'seedlab-experiments.xlsx')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    exporting.value = false
  }
}
async function exportLedger() {
  ledgerBusy.value = true
  try {
    const { data } = await api.get<Blob>('/export/catalog.xlsx', { responseType: 'blob' })
    saveFile(data, 'seedlab-catalog.xlsx')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    ledgerBusy.value = false
  }
}
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">材料清单与数据归档</div>
      <h1>导入与导出</h1>
      <p>导入种子材料清单后可继续创建实验；导出工作簿用于核对、交换和存档。</p>
    </div>
  </div>
  <div class="data-workspace-cards">
    <IntegratedMaterialImport />
    <section class="surface-panel integrated-import">
      <div class="panel-heading">
        <div class="data-card-icon">
          <el-icon><Download /></el-icon>
        </div>
        <div>
          <h2>导出实验数据</h2>
          <p>选择一个或多个实验，生成包含材料、发芽、幼苗测定等原始数据的 Excel 工作簿。</p>
        </div>
      </div>
      <label for="export-experiments">选择实验</label>
      <el-select
        id="export-experiments"
        v-model="selectedExperiments"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        placeholder="选择实验"
        class="export-experiment-select"
      >
        <el-option
          v-for="item in experiments"
          :key="item.id"
          :value="item.id"
          :label="`${item.name} · ${item.code}`"
        />
      </el-select>
      <p v-if="!experiments.length" class="wizard-empty">尚无实验，请先创建实验并录入实验数据。</p>
      <el-button
        type="primary"
        :icon="Download"
        :loading="exporting"
        :disabled="!selectedExperiments.length"
        @click="exportExperiments"
        >生成实验数据工作簿</el-button
      >
    </section>
    <section class="surface-panel integrated-import">
      <div class="panel-heading">
        <div class="data-card-icon">
          <el-icon><Files /></el-icon>
        </div>
        <div>
          <h2>导出物种与批次总表</h2>
          <p>导出当前系统中的物种和种子批次基础台账。</p>
        </div>
      </div>
      <p>
        一个工作簿包含物种、种子批次两张表，保留原始材料编号、数量和使用状态。该工作簿用于存档，不是导入模板。
      </p>
      <el-button :icon="Download" :loading="ledgerBusy" @click="exportLedger"
        >导出物种与批次总表</el-button
      >
    </section>
  </div>
</template>
