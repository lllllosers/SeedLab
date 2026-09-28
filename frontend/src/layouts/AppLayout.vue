<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
import { ElMessage } from 'element-plus'
import { errorMessage } from '../api/client'
import {
  DataAnalysis,
  Collection,
  Notebook,
  Box,
  UploadFilled,
  Clock,
  User,
  HomeFilled,
  ArrowDown,
  SwitchButton,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const title = computed(
  () =>
    ({
      dashboard: '工作台',
      taxa: '物种信息库',
      'taxon-detail': '物种详情',
      'seed-lots': '种子批次',
      experiments: '实验列表',
      'experiment-detail': '实验详情',
      data: '数据交换',
      audit: '操作记录',
      users: '用户管理',
    })[String(route.name)] || 'SeedLab',
)
async function logout() {
  try {
    await auth.logout()
    router.push('/login')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <router-link to="/" class="brand"
        ><span class="brand-icon"><span /></span
        ><span class="brand-copy"><b>SeedLab</b><small>种子试验管理系统</small></span></router-link
      >
      <div class="sidebar-divider" />
      <nav class="side-nav" aria-label="主导航">
        <div class="nav-label">总览</div>
        <router-link to="/" class="nav-link" exact-active-class="active"
          ><el-icon><HomeFilled /></el-icon><span>工作台</span></router-link
        >
        <div class="nav-label">实验管理</div>
        <router-link to="/experiments" class="nav-link" active-class="active"
          ><el-icon><Notebook /></el-icon><span>实验列表</span></router-link
        >
        <div class="nav-label">资源库</div>
        <router-link to="/taxa" class="nav-link" active-class="active"
          ><el-icon><Collection /></el-icon><span>物种信息库</span></router-link
        >
        <router-link to="/seed-lots" class="nav-link" active-class="active"
          ><el-icon><Box /></el-icon><span>种子批次</span></router-link
        >
        <div class="nav-label">数据</div>
        <router-link to="/data" class="nav-link" active-class="active"
          ><el-icon><UploadFilled /></el-icon><span>导入与导出</span></router-link
        >
        <div class="nav-label">系统</div>
        <router-link to="/audit" class="nav-link" active-class="active"
          ><el-icon><Clock /></el-icon><span>操作记录</span></router-link
        >
        <router-link v-if="auth.user?.is_admin" to="/users" class="nav-link" active-class="active"
          ><el-icon><User /></el-icon><span>用户管理</span></router-link
        >
      </nav>
      <div class="sidebar-foot"><span class="online-dot" />课题组内部工作空间</div>
    </aside>
    <div class="main-column">
      <header class="topbar">
        <div class="topbar-path">
          <span>SeedLab</span><span class="slash">/</span><strong>{{ title }}</strong>
        </div>
        <div class="topbar-right">
          <span class="topbar-date">科研数据工作空间</span
          ><el-dropdown trigger="click"
            ><button class="account">
              <span class="avatar">{{ auth.user?.display_name?.slice(0, 1) }}</span
              ><span class="account-name">{{ auth.user?.display_name }}</span
              ><el-icon><ArrowDown /></el-icon></button
            ><template #dropdown
              ><el-dropdown-menu
                ><el-dropdown-item disabled
                  >{{ auth.user?.username }} ·
                  {{ auth.user?.is_admin ? '管理员' : '成员' }}</el-dropdown-item
                ><el-dropdown-item divided @click="router.push('/change-password')"
                  >修改密码</el-dropdown-item
                ><el-dropdown-item @click="logout"
                  ><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item
                ></el-dropdown-menu
              ></template
            ></el-dropdown
          >
        </div>
      </header>
      <main class="page-content"><router-view /></main>
    </div>
  </div>
</template>
