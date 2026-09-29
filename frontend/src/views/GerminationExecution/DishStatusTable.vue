<script setup lang="ts">
import type { GerminationExecution } from '../../types'
import { dateTimeText } from '../../utils'
defineProps<{ execution: GerminationExecution }>()
</script>
<template>
  <div class="execution-section-head">
    <div>
      <h3>实际培养皿</h3>
      <p>累计发芽数、发芽率和剩余数量均由巡检事实动态计算。</p>
    </div>
    <el-tag type="success" effect="plain">{{ execution.dish_count }} 个培养皿</el-tag>
  </div>
  <div class="execution-table-wrap">
    <table class="execution-table">
      <thead>
        <tr>
          <th>培养皿编号</th>
          <th>物种 / 批次</th>
          <th>重复</th>
          <th>置床粒数</th>
          <th>置床时间</th>
          <th>累计发芽</th>
          <th>当前发芽率</th>
          <th>剩余未发芽</th>
          <th>已选幼苗</th>
          <th>最近巡检</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="dish in execution.dishes" :key="dish.id">
          <td>
            <b>{{ dish.code }}</b>
          </td>
          <td>
            <b>{{ dish.taxon_common_name || dish.taxon_scientific_name }}</b>
            <small v-if="dish.taxon_common_name">{{ dish.taxon_scientific_name }}</small>
            <small>{{ dish.seed_lot_code }}</small>
          </td>
          <td>R{{ dish.replicate_no }}</td>
          <td>{{ dish.seed_count }}</td>
          <td>{{ dateTimeText(dish.sown_at) }}</td>
          <td>
            <strong>{{ dish.cumulative_germinated }}</strong>
          </td>
          <td>
            <div class="rate-cell">
              <el-progress
                :percentage="dish.germination_rate"
                :show-text="false"
                :stroke-width="5"
              /><span>{{ dish.germination_rate }}%</span>
            </div>
          </td>
          <td>{{ dish.remaining_ungerminated }}</td>
          <td>{{ dish.sample_count }}</td>
          <td>{{ dateTimeText(dish.last_observed_at) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
