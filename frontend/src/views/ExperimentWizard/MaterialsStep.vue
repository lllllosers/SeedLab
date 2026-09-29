<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { AvailableLot, Taxon } from '../../types'
import { useClientPagination } from '../../composables/useClientPagination'

const selected = defineModel<AvailableLot[]>({ required: true })
const taxa = ref<Taxon[]>([])
const lots = ref<AvailableLot[]>([])
const search = ref('')
const taxonId = ref('')
const busy = ref(false)
const checked = ref<string[]>([])
const removal = ref<string[]>([])
const pickerOpen = ref(false)
const groups = computed(() => {
  const result = new Map<string, { id: string; name: string; scientific: string; code: string; lots: AvailableLot[] }>()
  for (const lot of lots.value) {
    if (!result.has(lot.taxon_id)) result.set(lot.taxon_id, {
      id: lot.taxon_id, name: lot.taxon_common_name || lot.taxon_scientific_name,
      scientific: lot.taxon_scientific_name, code: lot.taxon_code, lots: [],
    })
    result.get(lot.taxon_id)!.lots.push(lot)
  }
  return [...result.values()]
})
const selectedIds = computed(() => new Set(selected.value.map((lot) => lot.id)))
const { page, pageSize, pageItems, resetPage } = useClientPagination(groups)
function ordered(items: AvailableLot[]) {
  return [...items].sort((a, b) => a.sort_rank - b.sort_rank)
}
function selectAll() { checked.value = lots.value.filter((lot) => !selectedIds.value.has(lot.id)).map((lot) => lot.id) }
function addChecked() {
  selected.value = ordered([...selected.value, ...lots.value.filter((lot) => checked.value.includes(lot.id) && !selectedIds.value.has(lot.id))])
  checked.value = []
  pickerOpen.value = false
}
function removeChecked() {
  selected.value = selected.value.filter((lot) => !removal.value.includes(lot.id))
  removal.value = []
}

async function loadTaxa(term = '') {
  try {
    taxa.value = (await api.get<Taxon[]>('/taxa', { params: { q: term } })).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function loadLots() {
  busy.value = true
  try {
    lots.value = (
      await api.get<AvailableLot[]>('/experiments/available-seed-lots', {
        params: { q: search.value, taxon_id: taxonId.value || undefined },
      })
    ).data
    resetPage()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}
function add(lot: AvailableLot) {
  if (selected.value.some((item) => item.id === lot.id))
    return ElMessage.warning('该种子批次已选择')
  selected.value = ordered([...selected.value, lot])
}
onMounted(() => {
  loadTaxa()
  loadLots()
})
</script>

<template>
  <div class="wizard-step-copy">
    <h2>选择实验材料</h2>
    <p>从可用种子批次中挑选本次实验材料；同一物种可选择多个批次。</p>
  </div>
  <div class="material-picker-summary surface-panel">
    <strong>已加入实验 {{ selected.length }} 份材料</strong>
    <span>{{ selected.length ? selected.slice(0, 4).map((lot) => lot.taxon_common_name || lot.taxon_scientific_name).join('、') + (selected.length > 4 ? '……' : '') : '尚未加入材料，请打开选择窗口。' }}</span>
    <el-button type="primary" @click="pickerOpen = true">选择实验材料</el-button>
  </div>
  <el-dialog v-model="pickerOpen" title="选择实验材料" width="min(1100px, 96vw)" top="4vh" class="material-picker-dialog">
    <p class="wizard-help">按中文名、学名或编号查找。单批次物种可直接勾选，多批次物种展开后选择具体批次。</p>
    <div class="wizard-search-row">
    <el-select
      v-model="taxonId"
      filterable
      remote
      clearable
      placeholder="筛选物种（中文名、学名或编号）"
      :remote-method="loadTaxa"
      @change="loadLots"
    >
      <el-option
        v-for="taxon in taxa"
        :key="taxon.id"
        class="taxon-select-option"
        :label="taxon.common_name || taxon.scientific_name"
        :value="taxon.id"
      >
        <div class="taxon-option">
          <b>{{ taxon.common_name || taxon.scientific_name }}</b>
          <small>{{ taxon.common_name ? `${taxon.scientific_name} · ${taxon.code}` : taxon.code }}</small>
        </div>
      </el-option>
    </el-select>
    <el-input
      v-model="search"
      clearable
      placeholder="搜索中文名、学名、物种编号、批次编号或来源"
      @keyup.enter="loadLots"
      @clear="loadLots"
    />
    <el-button @click="loadLots">搜索</el-button>
  </div>
    <div class="wizard-list material-picker-list" v-loading="busy">
    <div class="wizard-bulk-actions">
      <el-button @click="selectAll">全选当前筛选结果</el-button>
      <el-button @click="checked = []">取消全选</el-button>
      <span>已勾选 {{ checked.length }} 个批次 · 已加入实验 {{ selected.length }} 个批次</span>
      <el-button type="primary" :disabled="!checked.length" @click="addChecked">加入已选材料（{{ checked.length }}）</el-button>
    </div>
    <el-collapse>
      <el-collapse-item v-for="group in pageItems" :key="group.id" :name="group.id">
        <template #title>
          <el-checkbox v-if="group.lots.length === 1" v-model="checked" :value="group.lots[0].id" :disabled="selectedIds.has(group.lots[0].id)" @click.stop aria-label="勾选该物种的唯一可用批次" />
          <div class="picker-group-label"><b>{{ group.name }}</b><small>{{ group.scientific }} · {{ group.code }} · {{ group.lots.length }} 个可用批次 · 已勾选 {{ group.lots.filter((lot) => checked.includes(lot.id)).length }} 个 · 已加入实验 {{ group.lots.filter((lot) => selectedIds.has(lot.id)).length }} 个</small></div>
        </template>
        <div v-for="lot in group.lots" :key="lot.id" class="wizard-list-row">
          <el-checkbox v-model="checked" :value="lot.id" :disabled="selectedIds.has(lot.id)" aria-label="选择种子批次" />
          <div><b>{{ lot.code }}</b>
            <small>原始材料编号：{{ lot.source_code || '未填写' }} · 来源：{{ lot.source || '未填写' }}</small>
            <small>采集/获得日期：{{ lot.collected_at?.slice(0, 10) || '未填写' }} · 数量：{{ lot.quantity ?? '未填写' }} · 备注：{{ lot.notes || '未填写' }}</small>
          </div>
          <el-button size="small" :disabled="selectedIds.has(lot.id)" @click="add(lot)">加入实验</el-button>
        </div>
      </el-collapse-item>
    </el-collapse>
    <div v-if="!lots.length" class="wizard-empty">
      没有可用的种子批次。请先在物种信息库新增物种，再到种子批次页面添加种子批次。
    </div>
    </div>
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" class="list-pagination" :page-sizes="[25, 50, 100]" layout="total, sizes, prev, pager, next" :total="groups.length" />
    <el-collapse class="selected-material-collapse"><el-collapse-item name="selected" :title="`已加入实验的材料（${selected.length}）`">
      <div class="wizard-bulk-actions"><el-button @click="removal = selected.map((lot) => lot.id)">全选已加入材料</el-button><el-button @click="removal = []">取消全选</el-button><el-button type="danger" :disabled="!removal.length" @click="removeChecked">批量移除（{{ removal.length }}）</el-button></div>
      <div class="wizard-list selected selected-material-list"><div v-for="(lot, index) in selected" :key="lot.id" class="wizard-list-row">
        <el-checkbox v-model="removal" :value="lot.id" aria-label="选择移除实验材料" />
        <div class="wizard-order">预计 {{ String(index + 1).padStart(3, '0') }}</div>
        <div class="grow"><b>{{ lot.taxon_common_name || lot.taxon_scientific_name }}</b><small v-if="lot.taxon_common_name">{{ lot.taxon_scientific_name }}</small><small>{{ lot.code }}</small></div>
        <el-button text type="danger" @click="selected = selected.filter((item) => item.id !== lot.id)">移除</el-button>
      </div><div v-if="!selected.length" class="wizard-empty">尚未加入材料，请先勾选批次。</div></div>
    </el-collapse-item></el-collapse>
    <template #footer><el-button @click="pickerOpen = false">关闭</el-button><el-button type="primary" :disabled="!checked.length" @click="addChecked">加入已勾选材料（{{ checked.length }}）</el-button></template>
  </el-dialog>
</template>
