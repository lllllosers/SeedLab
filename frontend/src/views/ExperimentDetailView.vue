<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, errorMessage } from '../api/client'
import type { Experiment, ExperimentStatus } from '../types'
import { dateText, statusLabels } from '../utils'
import { ArrowLeft, Box, Calendar, Notebook } from '@element-plus/icons-vue'

const route = useRoute(),
  router = useRouter(),
  item = ref<Experiment | null>(null),
  editorOpen = ref(false)
const form = reactive({ name: '', description: '', status: 'draft' as ExperimentStatus })
async function load() {
  try {
    item.value = (await api.get<Experiment>(`/experiments/${route.params.id}`)).data
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
function edit() {
  if (!item.value) return
  Object.assign(form, {
    name: item.value.name,
    description: item.value.description || '',
    status: item.value.status,
  })
  editorOpen.value = true
}
async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写实验名称')
  try {
    await api.patch(`/experiments/${route.params.id}`, {
      name: form.name.trim(),
      description: form.description.trim() || null,
      status: form.status,
    })
    ElMessage.success('实验已更新')
    editorOpen.value = false
    await load()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}
onMounted(load)
</script>
<template>
  <button class="back-link" @click="router.push('/experiments')">
    <el-icon><ArrowLeft /></el-icon>返回实验列表
  </button>
  <div v-if="item" class="page-heading detail-heading">
    <div>
      <div class="eyebrow">{{ item.code }} / EXPERIMENT PROFILE</div>
      <h1>{{ item.name }}</h1>
      <p>
        创建于 {{ dateText(item.created_at) }} <span class="middle-dot">·</span> {{ item.code }}
      </p>
    </div>
    <div class="heading-actions">
      <span class="status-pill large" :class="item.status">{{ statusLabels[item.status] }}</span
      ><el-button @click="edit">编辑信息</el-button>
    </div>
  </div>
  <div v-if="item" class="detail-grid">
    <section class="surface-panel detail-card">
      <div class="panel-heading">
        <div>
          <h3>实验概况</h3>
          <p>项目基础档案与状态</p>
        </div>
      </div>
      <dl class="info-list">
        <div>
          <dt>实验编号</dt>
          <dd>{{ item.code }}</dd>
        </div>
        <div>
          <dt>实验名称</dt>
          <dd>{{ item.name }}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{{ statusLabels[item.status] }}</dd>
        </div>
        <div>
          <dt>开始时间</dt>
          <dd>{{ dateText(item.started_at) }}</dd>
        </div>
        <div>
          <dt>结束时间</dt>
          <dd>{{ dateText(item.ended_at) }}</dd>
        </div>
        <div>
          <dt>实验说明</dt>
          <dd>{{ item.description || '—' }}</dd>
        </div>
      </dl>
    </section>
    <div class="detail-side">
      <section class="surface-panel detail-card">
        <div class="panel-heading">
          <div>
            <h3>实验材料</h3>
            <p>种子批次与材料配置</p>
          </div>
        </div>
        <div class="empty-inline compact">
          <el-icon><Box /></el-icon><b>材料配置即将开放</b
          ><span>数据关系已建立，后续阶段将提供配置界面。</span>
        </div>
      </section>
      <section class="surface-panel detail-card">
        <div class="panel-heading">
          <div>
            <h3>测定计划</h3>
            <p>动态时间点</p>
          </div>
        </div>
        <div class="empty-inline compact">
          <el-icon><Calendar /></el-icon><b>尚无测定计划</b
          ><span>后续可按实验设定任意测定日。</span>
        </div>
      </section>
    </div>
  </div>
  <el-dialog v-model="editorOpen" title="编辑实验" width="540px"
    ><el-form label-position="top"
      ><el-form-item label="实验名称 *"><el-input v-model="form.name" /></el-form-item
      ><el-form-item label="状态"
        ><el-select v-model="form.status" style="width: 100%"
          ><el-option label="草稿" value="draft" /><el-option
            label="进行中"
            value="active" /><el-option label="已完成" value="completed" /><el-option
            label="已取消"
            value="cancelled" /></el-select></el-form-item
      ><el-form-item label="实验说明"
        ><el-input v-model="form.description" type="textarea" :rows="4" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="editorOpen = false">取消</el-button
      ><el-button type="primary" @click="save">保存修改</el-button></template
    ></el-dialog
  >
</template>
