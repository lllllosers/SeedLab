<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../../api/client'
import type { AvailableLot, Taxon } from '../../types'

const selected = defineModel<AvailableLot[]>({ required: true })
const taxa = ref<Taxon[]>([])
const lots = ref<AvailableLot[]>([])
const search = ref('')
const taxonId = ref('')
const busy = ref(false)

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
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}
function add(lot: AvailableLot) {
  if (selected.value.some((item) => item.id === lot.id))
    return ElMessage.warning('该种子批次已选择')
  selected.value = [...selected.value, lot]
}
function move(index: number, delta: number) {
  const next = [...selected.value]
  const other = index + delta
  if (other < 0 || other >= next.length) return
  ;[next[index], next[other]] = [next[other]!, next[index]!]
  selected.value = next
}
onMounted(() => {
  loadTaxa()
  loadLots()
})
</script>

<template>
  <div class="wizard-step-copy">
    <h2>选择实验材料</h2>
    <p>先查找物种，再从可用种子批次中选择。本次实验可以包含多个批次。</p>
  </div>
  <div class="wizard-search-row">
    <el-select
      v-model="taxonId"
      filterable
      remote
      clearable
      placeholder="筛选物种"
      :remote-method="loadTaxa"
      @change="loadLots"
    >
      <el-option
        v-for="taxon in taxa"
        :key="taxon.id"
        :label="taxon.scientific_name"
        :value="taxon.id"
      />
    </el-select>
    <el-input
      v-model="search"
      clearable
      placeholder="搜索学名、物种编号或批次编号"
      @keyup.enter="loadLots"
      @clear="loadLots"
    />
    <el-button @click="loadLots">搜索</el-button>
  </div>
  <div class="wizard-list" v-loading="busy">
    <div v-for="lot in lots" :key="lot.id" class="wizard-list-row">
      <div>
        <b>{{ lot.taxon_name }}</b
        ><small
          >{{ lot.code }} · {{ lot.source || '来源未填写' }} · 登记数量
          {{ lot.quantity ?? '未知' }}</small
        >
      </div>
      <el-button
        type="primary"
        plain
        size="small"
        :disabled="selected.some((item) => item.id === lot.id)"
        @click="add(lot)"
        >加入实验</el-button
      >
    </div>
    <div v-if="!lots.length" class="wizard-empty">
      没有可用的种子批次。请先在物种信息库新增物种，再到种子批次页面添加种子批次。
    </div>
  </div>
  <h3 class="wizard-subheading">
    已选材料 <span>{{ selected.length }}</span>
  </h3>
  <div class="wizard-list selected">
    <div v-for="(lot, index) in selected" :key="lot.id" class="wizard-list-row">
      <div class="wizard-order">{{ index + 1 }}</div>
      <div class="grow">
        <b>{{ lot.taxon_name }}</b
        ><small>{{ lot.code }}</small>
      </div>
      <el-button text :disabled="index === 0" @click="move(index, -1)">上移</el-button>
      <el-button text :disabled="index === selected.length - 1" @click="move(index, 1)"
        >下移</el-button
      >
      <el-button
        text
        type="danger"
        @click="selected = selected.filter((item) => item.id !== lot.id)"
        >移除</el-button
      >
    </div>
    <div v-if="!selected.length" class="wizard-empty">尚未选择材料</div>
  </div>
</template>
