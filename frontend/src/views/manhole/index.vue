<template>
  <section class="page" data-module="manhole">
    <header class="page-head">
      <div>
        <h2>检查井管理</h2>
        <p class="page-desc">维护检查井，围绕井编号、所在道路、井盖类别、井室深度做登记、筛选与状态流转；超深度限值的井按口径自动列入重点清掏。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="readonly" @click="openCreate">登记检查井</button>
        <button class="btn" type="button" @click="exportRows">导出检查井清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>井编号</span>
        <input v-model="filters.keyword" placeholder="按井编号检索" />
      </label>
      <label class="filter-item">
        <span>所在道路</span>
        <input v-model="filters.road" placeholder="按所在道路检索" />
      </label>
      <label class="filter-item">
        <span>井盖类别</span>
        <input v-model="filters.cover" placeholder="按井盖类别检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-check">
        <input v-model="filters.key_only" type="checkbox" />
        只看重点清掏
      </label>
      <label class="filter-check">
        <input v-model="filters.urgent_only" type="checkbox" />
        只看催办井室
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>清掏级别</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '井编号'" class="link" type="button" @click="openDetail(row)">{{ row[column] ?? '—' }}</button>
            <span v-else>{{ displayValue(row, column) }}</span>
          </td>
          <td>
            <span v-if="row['重点清掏']" class="badge warn">重点清掏</span>
            <span v-else class="badge">常规</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
            <template v-if="!readonly">
              <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">
                {{ action }}
              </button>
              <button class="link" type="button" @click="openOwnership(row)">调整归属</button>
            </template>
            <span v-else class="readonly-tip">只读岗位不可操作</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的检查井记录</td>
        </tr>
      </tbody>
    </table>

    <section class="reminder-block">
      <h3>催办清单 <small>（共 {{ reminders.length }} 条，随检查井结论自动重算）</small></h3>
      <table v-if="reminders.length" class="data-table compact">
        <thead>
          <tr><th>井编号</th><th>所在道路</th><th>井盖类别</th><th>检查井状态</th><th>重点清掏</th><th>催办理由</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in reminders" :key="String(item.id)">
            <td>{{ item['井编号'] }}</td>
            <td>{{ item['所在道路'] }}</td>
            <td>{{ item['井盖类别'] }}</td>
            <td>{{ item['检查井状态'] }}</td>
            <td>{{ item['重点清掏'] ? '是' : '否' }}</td>
            <td>{{ item['催办理由'] }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">当前没有需要催办的井室。</p>
    </section>

    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记 / 更新检查井</h3>
        <p class="modal-tip">同一井编号再次提交会覆盖旧取值，旧值自动留档可在详情里回看。</p>
        <label v-for="field in formFields" :key="field" class="filter-item">
          <span>{{ field }}<em v-if="requiredFields.includes(field)">*</em></span>
          <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
        </label>
        <div class="modal-actions">
          <button class="btn primary" type="submit">提交</button>
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
        </div>
      </form>
    </div>

    <div v-if="ownershipTarget" class="modal-mask" @click.self="ownershipTarget = null">
      <form class="modal" @submit.prevent="submitOwnership">
        <h3>调整检查井归属</h3>
        <p class="modal-tip">{{ ownershipTarget['井编号'] }} 当前归属：{{ ownershipTarget['责任班组'] || '—' }}</p>
        <label class="filter-item">
          <span>责任班组</span>
          <input v-model="ownerValue" placeholder="请输入新的责任班组" />
        </label>
        <div class="modal-actions">
          <button class="btn primary" type="submit">保存归属</button>
          <button class="btn ghost" type="button" @click="ownershipTarget = null">取消</button>
        </div>
      </form>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal detail-modal">
        <h3>检查井详情 · {{ detail['井编号'] }}</h3>
        <table class="data-table compact">
          <tbody>
            <tr v-for="field in detailFields" :key="field">
              <th>{{ field }}</th>
              <td>{{ detail[field] ?? '—' }}</td>
            </tr>
            <tr>
              <th>口径识别</th>
              <td>{{ detail['口径mm'] != null ? `${detail['口径mm']}mm` : '无法识别' }}</td>
            </tr>
            <tr>
              <th>深度限值</th>
              <td>{{ detail['深度限值m'] }}m（超限即列入重点清掏）</td>
            </tr>
            <tr>
              <th>重点清掏</th>
              <td>{{ detail['重点清掏'] ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table>
        <h4>历史取值（按当时那版留档）</h4>
        <table class="data-table compact">
          <thead>
            <tr><th>版本</th><th>当时状态</th><th>责任班组</th><th>井室深度</th><th>井室尺寸</th></tr>
          </thead>
          <tbody>
            <tr v-for="version in [...(detail.history ?? [])].reverse()" :key="version.version">
              <td>v{{ version.version }}</td>
              <td>{{ version.status }}</td>
              <td>{{ version.values?.['责任班组'] ?? '—' }}</td>
              <td>{{ version.values?.['井室深度'] ?? '—' }}</td>
              <td>{{ version.values?.['井室尺寸'] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条检查井记录（与上方筛选条件一致）</span>
      <span v-if="readonly" class="readonly-tip">当前为只读岗位，仅可查看，不能改动状态与归属</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null | HistoryVersion[] | Record<string, unknown>[]>
type HistoryVersion = {
  version: number
  status: string
  values: Record<string, string | null>
}

const session = useSessionStore()
const readonly = computed(() => session.isReadonly)

const ENDPOINT = '/api/manhole'
const columns = ['井编号', '所在道路', '井盖类别', '井室深度', '井室尺寸', '上次清掏日', '责任班组', '检查井状态']
const detailFields = columns
const formFields = ['井编号', '所在道路', '井盖类别', '井室深度', '井室尺寸', '上次清掏日', '责任班组']
const requiredFields = ['井编号', '所在道路', '井盖类别']
const actions = ['安排清掏', '确认正常', '上报缺失', '废弃井室']
const statuses = ['待清掏', '正常使用', '井盖缺失', '已废弃']

const rows = ref<Row[]>([])
const reminders = ref<Row[]>([])
const stats = ref<{ label: string; value: number }[]>([
  { label: '在册检查井', value: 0 },
  { label: '待清掏井室', value: 0 },
  { label: '井盖缺失', value: 0 },
  { label: '重点检查井', value: 0 },
  { label: '催办条数', value: 0 },
])
const total = ref(0)
const errorMessage = ref('')
const filters = reactive({
  keyword: '',
  road: '',
  cover: '',
  status: '',
  key_only: false,
  urgent_only: false,
})

const createOpen = ref(false)
const createForm = ref<Record<string, string>>({})
const ownershipTarget = ref<Row | null>(null)
const ownerValue = ref('')
const detail = ref<(Row & { history?: HistoryVersion[] }) | null>(null)

function displayValue(row: Row, column: string) {
  // 列表与详情共用后端返回的同一口径，避免两套状态。
  return row[column] ?? '—'
}

function buildQuery(withBooleans = true) {
  const params = new URLSearchParams()
  if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
  if (filters.road.trim()) params.set('road', filters.road.trim())
  if (filters.cover.trim()) params.set('cover', filters.cover.trim())
  if (filters.status) params.set('status', filters.status)
  if (withBooleans && filters.key_only) params.set('key_only', 'true')
  if (withBooleans && filters.urgent_only) params.set('urgent_only', 'true')
  const query = params.toString()
  return query ? `?${query}` : ''
}

function resetFilters() {
  filters.keyword = ''
  filters.road = ''
  filters.cover = ''
  filters.status = ''
  filters.key_only = false
  filters.urgent_only = false
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export${buildQuery()}`, '_blank')
}

function openCreate() {
  if (readonly.value) {
    errorMessage.value = '只读岗位不能登记或更新检查井'
    return
  }
  createForm.value = Object.fromEntries(formFields.map((field) => [field, '']))
  createOpen.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const values = Object.fromEntries(
      formFields.map((field) => [field, createForm.value[field]?.trim() ?? '']).filter(([, value]) => value),
    )
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values }) })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.detail || payload.message || '检查井登记未生效')
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查井登记失败'
  }
}

async function runAction(action: string, row: Row) {
  if (readonly.value) {
    errorMessage.value = '只读岗位不能变更检查井状态'
    return
  }
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || '检查井动作未生效，请稍后重试')
    }
    if (payload.ok === false) {
      throw new Error(payload.message)
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查井操作失败'
  }
}

function openOwnership(row: Row) {
  if (readonly.value) {
    errorMessage.value = '只读岗位不能调整检查井归属'
    return
  }
  ownershipTarget.value = row
  ownerValue.value = String(row['责任班组'] ?? '')
}

async function submitOwnership() {
  if (!ownershipTarget.value) return
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${ownershipTarget.value.id}/ownership`, {
      method: 'POST',
      body: JSON.stringify({ values: { 责任班组: ownerValue.value.trim() } }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || '归属未调整成功')
    }
    if (payload.ok === false) {
      throw new Error(payload.message)
    }
    ownershipTarget.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归属调整失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('检查井详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查井详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const [listResponse, statsResponse, reminderResponse] = await Promise.all([
      request(`${ENDPOINT}${buildQuery()}`),
      request(`${ENDPOINT}/stats${buildQuery()}`),
      // 催办清单只受业务筛选影响，不被状态/重点过滤收窄，保证条数始终跟着结论重算。
      request(`${ENDPOINT}/reminders${buildQuery(false)}`),
    ])
    if (!listResponse.ok) throw new Error('检查井列表读取失败')
    if (!statsResponse.ok) throw new Error('检查井统计读取失败')
    if (!reminderResponse.ok) throw new Error('催办清单读取失败')
    const listPayload = await listResponse.json()
    const statsPayload = await statsResponse.json()
    const reminderPayload = await reminderResponse.json()
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    stats.value = statsPayload.items ?? stats.value
    reminders.value = reminderPayload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查井列表读取失败'
  }
}

onMounted(reload)
</script>
