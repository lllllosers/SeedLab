<script setup lang="ts">
import { computed } from 'vue'
import type { GerminationExecution } from '../../types'
import { dateTimeText } from '../../utils'
const props = defineProps<{ execution: GerminationExecution; materialId?: string | null }>()
defineEmits<{ showAll: [] }>()
const dishes = computed(() =>
  props.materialId
    ? props.execution.dishes.filter((dish) => dish.material_id === props.materialId)
    : props.execution.dishes,
)
</script>
<template>
  <div class="execution-section-head">
    <div>
      <h3>培养皿状态</h3>
      <p>累计发芽数、发芽率和剩余数量均由巡检事实动态计算。</p>
    </div>
    <div>
      <el-button v-if="materialId" link @click="$emit('showAll')">查看全部培养皿</el-button
      ><el-tag type="success" effect="plain">{{ dishes.length }} 个培养皿</el-tag>
    </div>
  </div>
  <div class="execution-table-wrap">
    <table class="execution-table">
      <thead>
        <tr>
          <th>现场编号</th>
          <th>物种 / 批次</th>
          <th>重复</th>
          <th>置床粒数</th>
          <th>置床时间</th>
          <th>状态</th>
          <th>累计发芽</th>
          <th>当前发芽率</th>
          <th>剩余未发芽</th>
          <th>已选幼苗</th>
          <th>最近巡检</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="dish in dishes" :key="dish.id">
          <td>
            <b>{{ dish.field_number || '编号未确认' }}</b>
          </td>
          <td>
            <b>{{ dish.taxon_common_name || dish.taxon_scientific_name }}</b>
            <small v-if="dish.taxon_common_name">{{ dish.taxon_scientific_name }}</small>
            <small
              >原始材料编号：{{ dish.source_code || '未填写' }} · {{ dish.seed_lot_code }}</small
            >
          </td>
          <td>R{{ dish.replicate_no }}</td>
          <td>{{ dish.seed_count }}</td>
          <td>{{ dateTimeText(dish.sown_at) }}</td>
          <td>{{ dish.cancelled_at ? '已取消' : dish.sown_at ? '已置床' : '待置床' }}</td>
          <td>
            <strong>{{ dish.cumulative_germinated }}</strong>
          </td>
          <td>
            <div v-if="dish.sown_at && dish.observation_count" class="rate-cell">
              <el-progress
                :percentage="dish.germination_rate"
                :show-text="false"
                :stroke-width="5"
              /><span>{{ dish.germination_rate }}%</span>
            </div>
            <span v-else>—</span>
          </td>
          <td>{{ dish.remaining_ungerminated }}</td>
          <td>{{ dish.sample_count }}</td>
          <td>{{ dateTimeText(dish.last_observed_at) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
