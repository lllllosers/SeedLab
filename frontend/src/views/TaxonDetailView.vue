<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage } from '../api/client'
import type { SeedLot, Taxon } from '../types'
import { dateText } from '../utils'
import { ElMessage } from 'element-plus'
import { Box, Notebook } from '@element-plus/icons-vue'
import PageBackButton from '../components/PageBackButton.vue'

const route = useRoute()
const item = ref<Taxon | null>(null),
  lots = ref<SeedLot[]>([])
onMounted(async () => {
  try {
    item.value = (await api.get<Taxon>(`/taxa/${route.params.id}`)).data
    lots.value = (
      await api.get<SeedLot[]>('/seed-lots', { params: { taxon_id: route.params.id } })
    ).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})
</script>
<template>
  <PageBackButton to="/taxa" label="返回物种列表" />
  <div v-if="item" class="page-heading detail-heading">
    <div>
      <div class="eyebrow">物种编号 {{ item.code }}</div>
      <h1>{{ item.common_name || item.scientific_name }}</h1>
      <p>
        <i>{{ item.scientific_name }}</i> <span class="middle-dot">·</span>
        {{ item.family || '未填写科' }}
      </p>
    </div>
    <span class="status-pill large" :class="item.is_active ? 'active' : 'cancelled'">{{
      item.is_active ? '使用中' : '已停用'
    }}</span>
  </div>
  <div v-if="item" class="detail-grid">
    <section class="surface-panel detail-card">
      <div class="panel-heading">
        <div>
          <h3>基本信息</h3>
          <p>物种档案</p>
        </div>
      </div>
      <dl class="info-list">
        <div>
          <dt>物种编号</dt>
          <dd>{{ item.code }}</dd>
        </div>
        <div>
          <dt>学名</dt>
          <dd>
            <i>{{ item.scientific_name }}</i>
          </dd>
        </div>
        <div>
          <dt>中文名 / 俗名</dt>
          <dd>{{ item.common_name || '—' }}</dd>
        </div>
        <div>
          <dt>科</dt>
          <dd>{{ item.family || '—' }}</dd>
        </div>
        <div><dt>属</dt><dd>{{ item.genus || '未填写' }}</dd></div>
        <div><dt>生活型</dt><dd>{{ item.life_form || '未填写' }}</dd></div>
        <div>
          <dt>创建时间</dt>
          <dd>{{ dateText(item.created_at) }}</dd>
        </div>
        <div>
          <dt>备注</dt>
          <dd>{{ item.notes || '—' }}</dd>
        </div>
      </dl>
    </section>
    <div class="detail-side">
      <section class="surface-panel detail-card">
        <div class="panel-heading">
          <div>
            <h3>种子批次</h3>
            <p>关联 {{ lots.length }} 个批次</p>
          </div>
          <router-link to="/seed-lots">查看全部</router-link>
        </div>
        <div v-if="!lots.length" class="empty-inline compact">
          <el-icon><Box /></el-icon><b>暂无种子批次</b
          ><span>可在种子批次页面添加并关联此物种。</span>
        </div>
        <div v-for="lot in lots" :key="lot.id" class="mini-row">
          <b>{{ lot.code }}</b
          ><small>原始材料编号：{{ lot.source_code || '未填写' }} · 来源：{{ lot.source || '未填写' }}</small>
        </div>
      </section>
      <section class="surface-panel detail-card">
        <div class="panel-heading">
          <div>
            <h3>试验履历</h3>
            <p>此物种相关的实验记录</p>
          </div>
        </div>
        <div class="empty-inline compact">
          <el-icon><Notebook /></el-icon><b>履历将在后续阶段开放</b
          ><span>这部分信息将在后续开放；现在可在实验列表查看已建立的实验。</span>
        </div>
      </section>
      <section class="surface-panel detail-card">
        <div class="panel-heading"><div><h3>外部资料</h3><p>资料扩展区域</p></div></div>
        <p>联网查询将在后续阶段评估。当前以本系统已登记的物种信息为准。</p>
      </section>
    </div>
  </div>
</template>
