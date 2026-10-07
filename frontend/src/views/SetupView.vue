<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../shared/api/client'
import { useAuth } from '../stores/auth'
import type { User } from '../types'

const router = useRouter()
const auth = useAuth()
const saving = ref(false)
const form = reactive({
  bootstrap_token: '',
  username: '',
  display_name: '',
  password: '',
  confirm_password: '',
})
async function submit() {
  if (form.password.length < 8 || form.password.length > 128)
    return ElMessage.warning('密码须为 8 至 128 位')
  if (form.password !== form.confirm_password) return ElMessage.warning('两次输入的密码不一致')
  saving.value = true
  try {
    const { data } = await api.post<{ user: User; csrf_token: string }>('/setup/bootstrap', form)
    auth.apply(data)
    ElMessage.success('管理员初始化完成')
    router.replace('/')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-story">
      <div class="login-story-inner">
        <div class="login-eyebrow"><span class="eyebrow-line" />种子试验管理系统</div>
        <h1>为课题组建立<br />第一个安全入口。</h1>
        <p>初始化完成后，这个入口会关闭。<br />成员账号由管理员统一创建。</p>
        <div class="story-foot">SeedLab <span>·</span> 种子试验管理系统</div>
      </div>
    </div>
    <div class="login-panel">
      <div class="login-panel-inner setup-panel-inner">
        <div class="mobile-brand">
          <span class="brand-icon"><span /></span><b>SeedLab</b>
        </div>
        <div class="login-kicker">首次部署</div>
        <h2>初始化管理员</h2>
        <p class="login-help">请从运行 SeedLab 的服务器本机终端获取一次性初始化码。</p>
        <form @submit.prevent="submit">
          <label class="field-label" for="bootstrap-token">首次初始化码</label>
          <el-input
            id="bootstrap-token"
            v-model="form.bootstrap_token"
            size="large"
            autocomplete="off"
            placeholder="输入本机终端显示的一次性初始化码"
          />
          <label class="field-label" for="setup-username">管理员用户名</label>
          <el-input
            id="setup-username"
            v-model="form.username"
            size="large"
            autocomplete="username"
            placeholder="3 至 80 位字母、数字或 _ . -"
          />
          <label class="field-label" for="setup-name">显示姓名</label>
          <el-input
            id="setup-name"
            v-model="form.display_name"
            size="large"
            placeholder="例如：课题组管理员"
          />
          <label class="field-label" for="setup-password">密码</label>
          <el-input
            id="setup-password"
            v-model="form.password"
            size="large"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="8 至 128 位，可使用密码短语"
          />
          <label class="field-label" for="setup-confirm">确认密码</label>
          <el-input
            id="setup-confirm"
            v-model="form.confirm_password"
            size="large"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="再次输入密码"
          />
          <button class="login-submit" type="submit" :disabled="saving">
            {{ saving ? '正在初始化…' : '创建首个管理员' }}
          </button>
        </form>
        <div class="login-note">
          <span class="lock-dot" />初始化码不会在网页中显示；完成后立即失效
        </div>
      </div>
    </div>
  </div>
</template>
