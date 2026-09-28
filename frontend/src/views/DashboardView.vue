<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage } from '../api/client'
import type { Dashboard } from '../types'
import { actionLabels, dateText, entityLabels, statusLabels } from '../utils'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  Collection,
  Box,
  Notebook,
  Timer,
  Plus,
  DataAnalysis,
} from '@element-plus/icons-vue'

const router = useRouter()
const data = ref<Dashboard | null>(null)
onMounted(async () => {
  try {
    data.value = (await api.get<Dashboard>('/dashboard')).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
})
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">WORKSPACE OVERVIEW</div>
      <h1>工作台</h1>
      <p>掌握种质资源与实验进展，继续今天的研究工作。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="router.push('/experiments')">新建实验</el-button>
  </div>
  <div class="welcome-banner">
    <div>
      <div class="banner-kicker">SEEDLAB / RESEARCH</div>
      <h2>从可靠的记录开始，<br />积累可追溯的研究数据。</h2>
      <p>物种、批次与实验逐步关联，帮助课题组保留每一次试验的来龙去脉。</p>
      <router-link to="/taxa"
        >进入物种信息库 <el-icon><ArrowRight /></el-icon
      ></router-link>
    </div>
    <div class="banner-art">
      <div class="art-ring r1" />
      <div class="art-ring r2" />
      <div class="art-seed s1" />
      <div class="art-seed s2" />
      <div class="art-seed s3" />
    </div>
  </div>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-icon mint">
        <el-icon><Collection /></el-icon>
      </div>
      <div class="stat-label">物种总数</div>
      <div class="stat-value">{{ data?.taxa ?? '—' }}</div>
      <router-link to="/taxa"
        >查看物种 <el-icon><ArrowRight /></el-icon
      ></router-link>
    </div>
    <div class="stat-card">
      <div class="stat-icon sand">
        <el-icon><Box /></el-icon>
      </div>
      <div class="stat-label">种子批次数</div>
      <div class="stat-value">{{ data?.seed_lots ?? '—' }}</div>
      <router-link to="/seed-lots"
        >查看批次 <el-icon><ArrowRight /></el-icon
      ></router-link>
    </div>
    <div class="stat-card">
      <div class="stat-icon blue">
        <el-icon><Notebook /></el-icon>
      </div>
      <div class="stat-label">实验总数</div>
      <div class="stat-value">{{ data?.experiments ?? '—' }}</div>
      <router-link to="/experiments"
        >查看实验 <el-icon><ArrowRight /></el-icon
      ></router-link>
    </div>
    <div class="stat-card">
      <div class="stat-icon rose">
        <el-icon><Timer /></el-icon>
      </div>
      <div class="stat-label">进行中实验</div>
      <div class="stat-value">{{ data?.active_experiments ?? '—' }}</div>
      <router-link to="/experiments"
        >查看进展 <el-icon><ArrowRight /></el-icon
      ></router-link>
    </div>
  </div>
  <div class="dashboard-columns">
    <section class="surface-panel">
      <div class="panel-heading">
        <div>
          <h3>最近实验</h3>
          <p>最近创建的实验项目</p>
        </div>
        <router-link to="/experiments"
          >全部实验 <el-icon><ArrowRight /></el-icon
        ></router-link>
      </div>
      <div v-if="!data?.recent_experiments.length" class="empty-inline">
        <el-icon><Notebook /></el-icon><b>尚无实验</b><span>创建第一个实验，开始积累试验履历。</span
        ><el-button plain @click="router.push('/experiments')">前往创建</el-button>
      </div>
      <router-link
        v-for="item in data?.recent_experiments"
        :key="item.id"
        :to="`/experiments/${item.id}`"
        class="activity-row"
        ><span class="activity-icon"
          ><el-icon><Notebook /></el-icon></span
        ><span class="activity-main"
          ><b>{{ item.name }}</b
          ><small>{{ item.code }}</small></span
        ><span class="status-pill" :class="item.status">{{
          statusLabels[item.status]
        }}</span></router-link
      >
    </section>
    <section class="surface-panel">
      <div class="panel-heading">
        <div>
          <h3>最近操作</h3>
          <p>重要数据的变更记录</p>
        </div>
        <router-link to="/audit"
          >操作记录 <el-icon><ArrowRight /></el-icon
        ></router-link>
      </div>
      <div v-if="!data?.recent_actions.length" class="empty-inline">
        <el-icon><DataAnalysis /></el-icon><b>暂无操作记录</b
        ><span>创建物种、批次或实验后，这里会显示动态。</span>
      </div>
      <div v-for="item in data?.recent_actions" :key="item.id" class="activity-row">
        <span class="activity-icon muted"
          ><el-icon><DataAnalysis /></el-icon></span
        ><span class="activity-main"
          ><b
            >{{ actionLabels[item.action] || item.action
            }}{{ entityLabels[item.entity_type] || item.entity_type }}</b
          ><small>{{ dateText(item.created_at) }}</small></span
        >
      </div>
    </section>
  </div>
</template>
