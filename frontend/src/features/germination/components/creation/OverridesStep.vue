<script setup lang="ts">
import type { AvailableLot, ExperimentMaterialInput, ExperimentProtocol } from '../../index'
defineProps<{ lots: AvailableLot[]; protocol: ExperimentProtocol }>()
const materials = defineModel<ExperimentMaterialInput[]>({ required: true })
</script>
<template>
  <div class="wizard-step-copy">
    <h2>特殊材料参数</h2>
    <p>只填写需要与默认方案不同的数值。留空表示继承实验默认值。</p>
  </div>
  <div v-for="(material, index) in materials" :key="material.seed_lot_id" class="override-card">
    <div class="override-title">
      <span class="wizard-order">{{ index + 1 }}</span>
      <div>
        <b>{{ lots[index]?.taxon_common_name || lots[index]?.taxon_scientific_name }}</b>
        <small v-if="lots[index]?.taxon_common_name">{{ lots[index]?.taxon_scientific_name }}</small>
        <small>{{ lots[index]?.code }}</small>
      </div>
    </div>
    <div class="wizard-form-grid">
      <el-form-item :label="`每皿种子数（默认 ${protocol.seeds_per_dish}）`"
        ><el-input-number
          v-model="material.seeds_per_dish_override"
          :min="1"
          :precision="0"
          :placeholder="String(protocol.seeds_per_dish)"
          controls-position="right"
      /></el-form-item>
      <el-form-item :label="`重复数（默认 ${protocol.replicate_count}）`"
        ><el-input-number
          v-model="material.replicate_count_override"
          :min="1"
          :precision="0"
          :placeholder="String(protocol.replicate_count)"
          controls-position="right"
      /></el-form-item>
      <el-form-item :label="`取样数（默认 ${protocol.sample_count}）`"
        ><el-input-number
          v-model="material.sample_count_override"
          :min="1"
          :precision="0"
          :placeholder="String(protocol.sample_count)"
          controls-position="right"
      /></el-form-item>
    </div>
  </div>
</template>
