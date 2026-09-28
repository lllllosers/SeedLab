<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '../stores/auth'
import { errorMessage } from '../api/client'
import { ArrowRight } from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuth()
const username = ref('')
const password = ref('')
const loading = ref(false)
async function submit() {
  if (!username.value || !password.value) return ElMessage.warning('请输入用户名和密码')
  loading.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    router.push('/')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
</script>
<template>
  <div class="login-page">
    <div class="login-story">
      <div class="login-story-inner">
        <div class="login-eyebrow"><span class="eyebrow-line" />SEED RESEARCH WORKSPACE</div>
        <div class="login-illustration">
          <div class="orbit orbit-one" />
          <div class="orbit orbit-two" />
          <div class="seed-body" />
          <div class="sprout stem" />
          <div class="sprout leaf leaf-left" />
          <div class="sprout leaf leaf-right" />
          <div class="soil-line" />
        </div>
        <h1>让每一粒种子，<br />都有完整的试验履历。</h1>
        <p>从物种信息、种子批次到实验记录，<br />在一个清晰、可靠的工作空间里持续积累。</p>
        <div class="story-foot">SeedLab <span>·</span> 种子试验管理系统</div>
      </div>
    </div>
    <div class="login-panel">
      <div class="login-panel-inner">
        <div class="mobile-brand">
          <span class="brand-icon"><span /></span><b>SeedLab</b>
        </div>
        <div class="login-kicker">欢迎回来</div>
        <h2>登录 SeedLab</h2>
        <p class="login-help">使用课题组分配的账号继续工作。</p>
        <form @submit.prevent="submit">
          <label class="field-label" for="username">用户名</label
          ><el-input
            id="username"
            v-model="username"
            size="large"
            placeholder="请输入用户名"
            autocomplete="username"
          /><label class="field-label" for="password">密码</label
          ><el-input
            id="password"
            v-model="password"
            size="large"
            type="password"
            show-password
            placeholder="请输入密码"
            autocomplete="current-password"
          /><button class="login-submit" type="submit" :disabled="loading">
            {{ loading ? '正在登录…' : '登录工作空间' }}<el-icon><ArrowRight /></el-icon>
          </button>
        </form>
        <div class="login-note"><span class="lock-dot" />仅限课题组成员访问 · 账号由管理员创建</div>
      </div>
      <div class="login-copyright">© 2026 SeedLab · Steven_Chen &amp; SS_Zhong</div>
    </div>
  </div>
</template>
