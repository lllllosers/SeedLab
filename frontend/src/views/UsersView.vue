<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { User } from '../types'
import { Plus } from '@element-plus/icons-vue'

const items = ref<User[]>([]),
  editorOpen = ref(false)
const form = reactive({ username: '', display_name: '', password: '', is_admin: false })
async function load() {
  try {
    items.value = (await api.get<User[]>('/users')).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
async function save() {
  if (form.password.length < 10) return ElMessage.warning('密码至少 10 位')
  try {
    await api.post('/users', form)
    ElMessage.success('用户已创建')
    editorOpen.value = false
    Object.assign(form, { username: '', display_name: '', password: '', is_admin: false })
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">SYSTEM / TEAM</div>
      <h1>用户管理</h1>
      <p>为课题组成员创建访问账号。当前采用管理员与普通成员两级权限。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="editorOpen = true">新增成员</el-button>
  </div>
  <div class="surface-panel table-panel">
    <div class="table-toolbar">
      <div class="toolbar-title">
        <h3>团队成员</h3>
        <span>{{ items.length }} 位成员</span>
      </div>
    </div>
    <el-table :data="items" class="data-table"
      ><el-table-column prop="display_name" label="姓名" min-width="180" /><el-table-column
        prop="username"
        label="用户名"
        min-width="180"
      /><el-table-column label="角色" width="130"
        ><template #default="{ row }"
          ><span class="status-pill" :class="row.is_admin ? 'active' : 'draft'">{{
            row.is_admin ? '管理员' : '普通成员'
          }}</span></template
        ></el-table-column
      ><el-table-column label="状态" width="130"
        ><template #default="{ row }">{{
          row.is_active ? '启用' : '停用'
        }}</template></el-table-column
      ></el-table
    >
  </div>
  <el-dialog v-model="editorOpen" title="新增成员" width="500px"
    ><el-form label-position="top"
      ><el-form-item label="用户名 *"
        ><el-input v-model="form.username" autocomplete="off" /></el-form-item
      ><el-form-item label="显示姓名 *"><el-input v-model="form.display_name" /></el-form-item
      ><el-form-item label="初始密码 *"
        ><el-input
          v-model="form.password"
          type="password"
          show-password
          autocomplete="new-password" /></el-form-item
      ><el-form-item
        ><el-checkbox v-model="form.is_admin">赋予管理员权限</el-checkbox></el-form-item
      ></el-form
    ><template #footer
      ><el-button @click="editorOpen = false">取消</el-button
      ><el-button type="primary" @click="save">创建成员</el-button></template
    ></el-dialog
  >
</template>
