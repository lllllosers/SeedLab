<script setup lang="ts">
import type { ExperimentProtocol } from '../../index'
const protocol = defineModel<ExperimentProtocol>({ required: true })
</script>
<template>
  <div class="wizard-step-copy">
    <h2>幼苗取样规则</h2>
    <p>当前采用按发芽顺序取前 N 株。实际样本将在后续实验执行阶段产生。</p>
  </div>
  <div class="wizard-rule-card"><b>前 N 株发芽幼苗</b><span>当前唯一支持的取样方式</span></div>
  <el-form-item label="取样数 N"
    ><el-input-number
      v-model="protocol.sample_count"
      :min="1"
      :precision="0"
      controls-position="right"
  /></el-form-item>
  <el-form-item label="取样范围">
    <el-radio-group v-model="protocol.sample_scope" class="wizard-radio-grid">
      <el-radio-button value="per_dish">每个培养皿取 N 株</el-radio-button>
      <el-radio-button value="per_material">每个实验材料合计取 N 株</el-radio-button>
    </el-radio-group>
  </el-form-item>
  <p class="wizard-help">
    每皿取样时，N 不能超过该材料每皿置床种子数；每材料取样时，N 不能超过该材料的“每皿种子数 ×
    重复数”。
  </p>
</template>
