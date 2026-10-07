<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../shared/api/client'
import { useAuth } from '../stores/auth'

const router = useRouter()
const auth = useAuth()
const saving = ref(false)
const form = reactive({ current_password: '', new_password: '', confirm_password: '' })
async function submit() {
  if (form.new_password.length < 8 || form.new_password.length > 128)
    return ElMessage.warning('新密码须为 8 至 128 位')
  if (form.new_password !== form.confirm_password)
    return ElMessage.warning('两次输入的新密码不一致')
  saving.value = true
  try {
    await api.post('/auth/change-password', form)
    auth.forget()
    ElMessage.success('密码已修改，请重新登录')
    router.replace('/login')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
async function logout() {
  try {
    await auth.logout()
    router.replace('/login')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-story">
      <div class="login-story-inner">
        <div class="login-eyebrow"><span class="eyebrow-line" />种子试验管理系统</div>
        <h1>保护账号，<br />继续安心记录实验。</h1>
        <p>设置只有你知道的新密码。<br />修改成功后需要重新登录。</p>
        <div class="story-foot">SeedLab <span>·</span> 种子试验管理系统</div>
      </div>
    </div>
    <div class="login-panel">
      <div class="login-panel-inner">
        <div class="mobile-brand">
          <span class="brand-icon"><span /></span><b>SeedLab</b>
        </div>
        <div class="login-kicker">账号安全</div>
        <h2>{{ auth.user?.must_change_password ? '请先修改初始密码' : '修改密码' }}</h2>
        <p class="login-help">
          {{
            auth.user?.must_change_password
              ? '临时密码仅供首次登录，完成修改后才能进入工作台。'
              : '修改后所有设备的会话都会失效。'
          }}
        </p>
        <form @submit.prevent="submit">
          <label class="field-label" for="current-password">当前密码</label>
          <el-input
            id="current-password"
            v-model="form.current_password"
            size="large"
            type="password"
            show-password
            autocomplete="current-password"
          />
          <label class="field-label" for="new-password">新密码</label>
          <el-input
            id="new-password"
            v-model="form.new_password"
            size="large"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="8 至 128 位，可使用密码短语"
          />
          <label class="field-label" for="confirm-password">确认新密码</label>
          <el-input
            id="confirm-password"
            v-model="form.confirm_password"
            size="large"
            type="password"
            show-password
            autocomplete="new-password"
          />
          <button class="login-submit" type="submit" :disabled="saving">
            {{ saving ? '正在保存…' : '保存新密码' }}
          </button>
        </form>
        <div class="account-secondary-actions">
          <el-button v-if="!auth.user?.must_change_password" link @click="router.push('/')"
            >返回工作台</el-button
          >
          <el-button link @click="logout">退出登录</el-button>
        </div>
      </div>
    </div>
  </div>
</template>
