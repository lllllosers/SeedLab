<script setup lang="ts">
import type { ExperimentProtocol } from '../../index'
const protocol = defineModel<ExperimentProtocol>({ required: true })
</script>
<template>
  <div class="wizard-step-copy">
    <h2>培养皿与观察计划</h2>
    <p>以下数值作为全部实验材料的默认方案。个别材料可以在第 6 步覆盖。</p>
  </div>
  <div class="wizard-form-grid">
    <el-form-item label="每个培养皿置床种子数"
      ><el-input-number
        v-model="protocol.seeds_per_dish"
        :min="1"
        :precision="0"
        controls-position="right"
    /></el-form-item>
    <el-form-item label="每个材料重复数"
      ><el-input-number
        v-model="protocol.replicate_count"
        :min="1"
        :precision="0"
        controls-position="right"
    /></el-form-item>
    <el-form-item label="计划发芽观察天数（可选）"
      ><el-input-number
        v-model="protocol.observation_period_days"
        @change="protocol.observation_period_days = $event ?? null"
        :min="1"
        :precision="0"
        controls-position="right"
      />
      <p class="wizard-help">
        仅用于预计日期和超期提醒，不会自动结束观察；不确定时可留空。
      </p></el-form-item
    >
  </div>
  <el-form-item label="发芽判定标准"
    ><el-input
      v-model="protocol.germination_criterion"
      type="textarea"
      :rows="3"
      placeholder="例如：胚根长度达到约定标准"
  /></el-form-item>
  <el-form-item label="实验方案备注"
    ><el-input
      v-model="protocol.summary"
      type="textarea"
      :rows="3"
      placeholder="记录环境条件、设计依据等"
  /></el-form-item>
</template>
