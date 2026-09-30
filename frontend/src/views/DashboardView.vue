<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage } from '../api/client'
import { useAuth } from '../stores/auth'
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
const auth = useAuth()
const data = ref<Dashboard | null>(null)
const greeting = computed(() => {
  const hour = new Date().getHours()
  return hour < 11 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
})
const activeTarget = computed(() =>
  data.value?.active_experiments === 1
    ? `/experiments/${data.value.active_experiment_ids[0]}/germination`
    : '/experiments?status=active',
)
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
      <div class="eyebrow">工作台</div>
      <h1>工作台</h1>
      <p>掌握种质资源与实验进展，继续今天的研究工作。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="router.push('/experiments')">新建实验</el-button>
  </div>
  <div class="welcome-banner">
    <div>
      <div class="banner-kicker">种子试验记录</div>
      <h2>{{ greeting }}，{{ auth.user?.display_name || '研究伙伴' }}</h2>
      <p>
        {{
          data?.active_experiments
            ? `当前有 ${data.active_experiments} 个实验正在进行。`
            : '目前暂无进行中的实验。'
        }}从可靠记录开始，继续今天的研究工作。
      </p>
      <div class="dashboard-quick-actions">
        <router-link v-if="data?.active_experiments" :to="activeTarget"
          >继续实验 <el-icon><ArrowRight /></el-icon
        ></router-link>
        <router-link to="/experiments/new"
          >创建实验 <el-icon><ArrowRight /></el-icon
        ></router-link>
        <router-link to="/data"
          >导入种子材料 <el-icon><ArrowRight /></el-icon
        ></router-link>
      </div>
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
        >查看全部实验 <el-icon><ArrowRight /></el-icon
      ></router-link>
    </div>
    <div class="stat-card">
      <div class="stat-icon rose">
        <el-icon><Timer /></el-icon>
      </div>
      <div class="stat-label">进行中实验</div>
      <div class="stat-value">{{ data?.active_experiments ?? '—' }}</div>
      <span v-if="!data?.active_experiments">暂无进行中实验</span>
      <router-link v-else :to="activeTarget"
        >{{ data?.active_experiments === 1 ? '继续实验' : '查看进行中实验' }}
        <el-icon><ArrowRight /></el-icon
      ></router-link>
    </div>
  </div>
  <section v-if="data" class="surface-panel dashboard-measurement">
    <div class="dashboard-measurement-header">
      <div>
        <h3>今日幼苗测定</h3>
        <p>按发芽判定日期安排的根长、苗长任务</p>
      </div>
    </div>
    <div class="dashboard-measurement-body">
      <p>
        今日待测 {{ data.measurement.due_today_count }} 项 · 已逾期
        {{ data.measurement.overdue_count }} 项
      </p>
      <div v-if="!data.measurement.experiments.length" class="empty-inline">
        目前没有需要处理的幼苗测定。可先完成发芽巡检，选出幼苗后再查看。
      </div>
      <router-link
        v-for="item in data.measurement.experiments"
        :key="item.id"
        class="activity-row"
        :to="`/experiments/${item.id}/germination?tab=measurement`"
        ><span class="activity-main"
          ><b>{{ item.name }}</b
          ><small
            >{{ item.code }} · 今日待测 {{ item.due_today_count }} · 已逾期
            {{ item.overdue_count }} · 涉及材料 {{ item.material_count }}</small
          ></span
        ><span>进入测定 →</span></router-link
      >
    </div>
  </section>
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
            >{{ actionLabels[item.action] || '操作'
            }}{{ entityLabels[item.entity_type] || '相关数据' }}</b
          ><small>{{ dateText(item.created_at) }}</small></span
        >
      </div>
    </section>
  </div>
</template>
