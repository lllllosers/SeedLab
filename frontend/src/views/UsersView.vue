<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { api, errorMessage } from '../api/client'
import { useAuth } from '../stores/auth'
import type { User } from '../types'

const auth = useAuth()
const items = ref<User[]>([])
const createOpen = ref(false)
const editOpen = ref(false)
const resetOpen = ref(false)
const saving = ref(false)
const selected = ref<User | null>(null)
const createForm = reactive({ username: '', display_name: '', password: '', is_admin: false })
const editName = ref('')
const temporaryPassword = ref('')

async function load() {
  try {
    items.value = (await api.get<User[]>('/users')).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
function passwordValid(password: string) {
  if (password.length < 8 || password.length > 128) {
    ElMessage.warning('密码须为 8 至 128 位')
    return false
  }
  return true
}
async function create() {
  if (!passwordValid(createForm.password)) return
  saving.value = true
  try {
    await api.post('/users', createForm)
    ElMessage.success('成员已创建，首次登录须修改临时密码')
    createOpen.value = false
    Object.assign(createForm, { username: '', display_name: '', password: '', is_admin: false })
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
function beginEdit(user: User) {
  selected.value = user
  editName.value = user.display_name
  editOpen.value = true
}
async function saveEdit() {
  if (!selected.value) return
  saving.value = true
  try {
    await api.patch(`/users/${selected.value.id}`, { display_name: editName.value.trim() })
    editOpen.value = false
    ElMessage.success('姓名已更新')
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
async function changeRole(user: User) {
  const next = !user.is_admin
  try {
    await ElMessageBox.confirm(
      `将 ${user.display_name} 设为${next ? '管理员' : '普通成员'}？`,
      '确认角色变更',
    )
    await api.patch(`/users/${user.id}`, { is_admin: next })
    ElMessage.success('角色已更新')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
async function changeActive(user: User) {
  const next = !user.is_active
  try {
    await ElMessageBox.confirm(
      `${next ? '启用' : '停用'} ${user.display_name}？${next ? '' : '该账号的所有会话将立即失效。'}`,
      '确认账号状态',
    )
    await api.patch(`/users/${user.id}`, { is_active: next })
    ElMessage.success(next ? '账号已启用' : '账号已停用')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}
function beginReset(user: User) {
  selected.value = user
  temporaryPassword.value = ''
  resetOpen.value = true
}
async function saveReset() {
  if (!selected.value || !passwordValid(temporaryPassword.value)) return
  saving.value = true
  try {
    await api.post(`/users/${selected.value.id}/reset-password`, {
      password: temporaryPassword.value,
    })
    temporaryPassword.value = ''
    resetOpen.value = false
    ElMessage.success('密码已重置，成员下次登录须修改临时密码')
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">SYSTEM / TEAM</div>
      <h1>用户管理</h1>
      <p>管理员创建成员并管理账号状态。临时密码首次登录后必须修改。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="createOpen = true">新增成员</el-button>
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <div class="toolbar-title">
        <h3>团队成员</h3>
        <span>{{ items.length }} 位成员</span>
      </div>
    </div>
    <el-table :data="items" class="data-table">
      <el-table-column prop="display_name" label="姓名" min-width="140" />
      <el-table-column prop="username" label="用户名" min-width="150" />
      <el-table-column label="角色" width="120"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.is_admin ? 'active' : 'draft'">{{
            row.is_admin ? '管理员' : '普通成员'
          }}</span></template
        ></el-table-column
      >
      <el-table-column label="状态" width="90"
        ><template #default="{ row }">{{
          row.is_active ? '启用' : '停用'
        }}</template></el-table-column
      >
      <el-table-column label="初始密码" width="130"
        ><template #default="{ row }">{{
          row.must_change_password ? '待修改' : '已完成'
        }}</template></el-table-column
      >
      <el-table-column label="操作" min-width="270"
        ><template #default="{ row }">
          <el-button link type="primary" @click="beginEdit(row)">编辑</el-button>
          <el-button link :disabled="row.id === auth.user?.id" @click="changeRole(row)">{{
            row.is_admin ? '设为成员' : '设为管理员'
          }}</el-button>
          <el-button link :disabled="row.id === auth.user?.id" @click="changeActive(row)">{{
            row.is_active ? '停用' : '启用'
          }}</el-button>
          <el-button
            link
            type="warning"
            :disabled="row.id === auth.user?.id"
            @click="beginReset(row)"
            >重置密码</el-button
          >
        </template></el-table-column
      >
    </el-table>
  </div>

  <el-dialog v-model="createOpen" title="新增成员" width="500px">
    <el-form label-position="top">
      <el-form-item label="用户名"
        ><el-input
          v-model="createForm.username"
          autocomplete="off"
          placeholder="3 至 80 位字母、数字或 _ . -"
      /></el-form-item>
      <el-form-item label="显示姓名"><el-input v-model="createForm.display_name" /></el-form-item>
      <el-form-item label="临时密码"
        ><el-input
          v-model="createForm.password"
          type="password"
          show-password
          autocomplete="new-password"
          placeholder="8 至 128 位"
      /></el-form-item>
      <el-form-item
        ><el-checkbox v-model="createForm.is_admin">赋予管理员权限</el-checkbox></el-form-item
      >
    </el-form>
    <p class="account-dialog-help">成员首次登录后必须修改临时密码，才能使用业务页面。</p>
    <template #footer
      ><el-button @click="createOpen = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="create">创建成员</el-button></template
    >
  </el-dialog>
  <el-dialog v-model="editOpen" title="编辑成员" width="460px">
    <el-form label-position="top"
      ><el-form-item label="显示姓名"><el-input v-model="editName" /></el-form-item
    ></el-form>
    <template #footer
      ><el-button @click="editOpen = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button></template
    >
  </el-dialog>
  <el-dialog v-model="resetOpen" title="重置成员密码" width="460px">
    <p class="account-dialog-help">
      将为
      {{ selected?.display_name }} 设置临时密码，并立即清除该账号所有会话。成员下次登录须自行改密。
    </p>
    <el-input
      v-model="temporaryPassword"
      type="password"
      show-password
      autocomplete="new-password"
      placeholder="临时密码，8 至 128 位"
    />
    <template #footer
      ><el-button @click="resetOpen = false">取消</el-button
      ><el-button type="primary" :loading="saving" @click="saveReset">确认重置</el-button></template
    >
  </el-dialog>
</template>
