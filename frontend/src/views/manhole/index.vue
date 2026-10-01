<template>
  <section class="page" data-module="manhole">
    <header class="page-head">
      <div>
        <h2>检查井管理</h2>
        <p class="page-desc">维护检查井，围绕井编号、所在道路、井盖类别、井室深度做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button v-if="!session.readonly" class="btn primary" type="button" @click="openSubmit()">登记 / 重新上报</button>
        <button class="btn" type="button" @click="exportRows">导出检查井清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>井编号</span>
        <input v-model="keyword" placeholder="按井编号检索" />
      </label>
      <label class="filter-item">
        <span>检查井状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item filter-check">
        <input v-model="onlyKey" type="checkbox" />
        <span>只看重点清掏（深度超限）</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>重点清掏</th>
          <th>可执行动作</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '检查井状态'">
              {{ row.status ?? row[column] ?? '—' }}
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <span v-if="row.重点清掏" class="tag tag-key">重点</span>
            <span v-else>—</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button v-if="!session.readonly" class="link" type="button" @click="openSubmit(row)">重新上报</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无检查井数据，可先登记检查井</td>
        </tr>
      </tbody>
    </table>

    <section v-if="urgings.length" class="urging-panel">
      <h3>催办清单（{{ urgings.length }} 条，随结论实时重算）</h3>
      <ul>
        <li v-for="item in urgings" :key="`${item.检查井id}-${item.催办事项}`">
          {{ item.井编号 }} · {{ item.所在道路 }} · 责任班组：{{ item.责任班组 ?? '—' }}
          → {{ item.催办事项 }}（{{ item.检查井状态 }}）
          <span v-if="item.重点清掏" class="tag tag-key">重点</span>
        </li>
      </ul>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条检查井记录（与上方统计同一套口径）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <header class="modal-head">
          <h3>检查井详情 · {{ detail.井编号 }}</h3>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ column === '检查井状态' ? (detail.status ?? detail[column]) : (detail[column] ?? '—') }}</dd>
          </template>
          <dt>重点清掏</dt>
          <dd>{{ detail.重点清掏 ? `是（井室深度超过 ${depthLimit} 米限值）` : '否' }}</dd>
        </dl>
        <h4>历史取值（旧值按当时那版保留）</h4>
        <ul v-if="detailHistory.length" class="history-list">
          <li v-for="(h, idx) in detailHistory" :key="idx">
            <span class="history-time">{{ h.time }}</span>
            来源「{{ h.来源 }}」→ 当时状态：{{ h.状态 }}；
            深度 {{ h.井室深度 ?? '—' }}；责任班组 {{ h.责任班组 ?? '—' }}
            <span v-if="h.重点清掏" class="tag tag-key">重点</span>
          </li>
        </ul>
        <p v-else class="empty-state">该井还没有历史版本。</p>
      </div>
    </div>

    <div v-if="submitOpen" class="modal-mask" @click.self="submitOpen = false">
      <div class="modal">
        <header class="modal-head">
          <h3>{{ submitForm.id ? '重新上报（后到的一份覆盖）' : '登记检查井' }}</h3>
          <button class="link" type="button" @click="submitOpen = false">关闭</button>
        </header>
        <form class="submit-form" @submit.prevent="submitEntry">
          <label v-for="field in editableFields" :key="field">
            <span>{{ field }}{{ requiredFields.includes(field) ? ' *' : '' }}</span>
            <input
              v-model="submitForm[field]"
              :disabled="session.readonly && field === '责任班组'"
              :placeholder="readonlyHint(field)"
            />
          </label>
          <p v-if="session.readonly" class="error-text">只读岗位：责任班组（归属）不可修改。</p>
          <div class="submit-actions">
            <button class="btn primary" type="submit">提交</button>
            <button class="btn ghost" type="button" @click="submitOpen = false">取消</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null | HistoryItem[]>
type HistoryItem = {
  time: string
  来源: string
  状态: string
  重点清掏: boolean
  [key: string]: string | boolean | undefined
}
type Urging = {
  检查井id: number
  井编号: string
  所在道路: string
  责任班组: string | null
  催办事项: string
  检查井状态: string
  重点清掏: boolean
}
type Stats = Record<string, number>

const ENDPOINT = '/api/manhole'
const session = useSessionStore()

const columns = ["井编号", "所在道路", "井盖类别", "井室深度", "井室尺寸", "上次清掏日", "责任班组", "检查井状态"]
const editableFields = ["井编号", "所在道路", "井盖类别", "井室深度", "井室尺寸", "上次清掏日", "责任班组"]
const requiredFields = ["井编号", "所在道路", "井盖类别"]
const actions = ["安排清掏", "确认正常", "上报缺失", "废弃井室"]
const statuses = ["待清掏", "正常使用", "井盖缺失", "已废弃"]
const depthLimit = 3

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const stats = ref<Stats>({})
const urgings = ref<Urging[]>([])

const keyword = ref('')
const statusFilter = ref('')
const onlyKey = ref(false)

const detail = ref<Row | null>(null)
const submitOpen = ref(false)
const submitForm = reactive<Record<string, string>>({})

const statCards = computed(() => [
  { label: '在册检查井', value: stats.value['在册检查井'] ?? 0 },
  { label: '待清掏井室', value: stats.value['待清掏井室'] ?? 0 },
  { label: '井盖缺失', value: stats.value['井盖缺失'] ?? 0 },
  { label: '重点检查井', value: stats.value['重点检查井'] ?? 0 },
  { label: '催办清单', value: stats.value['催办清单'] ?? 0 },
])

const detailHistory = computed<HistoryItem[]>(() => {
  const history = detail.value?.history
  return Array.isArray(history) ? [...history].reverse() : []
})

function availableActions(row: Row): string[] {
  // 已废弃为终态，不再给出可改变结果的动作；当前状态对应的确认类动作保留为“重复确认”
  if (row.status === '已废弃') {
    return []
  }
  return actions
}

function readonlyHint(field: string): string {
  if (session.readonly && field === '责任班组') {
    return '只读岗位不可调整归属'
  }
  return `请输入${field}`
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  onlyKey.value = false
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openDetail(row: Row) {
  // 直接取列表这一行，详情与列表永远是同一口径、同一结果
  detail.value = row
}

function openSubmit(row?: Row) {
  errorMessage.value = ''
  editableFields.forEach((field) => {
    submitForm[field] = row ? String(row[field] ?? '') : ''
  })
  submitForm.id = row ? String(row.id) : ''
  submitOpen.value = true
}

async function submitEntry() {
  const values: Record<string, string> = {}
  editableFields.forEach((field) => {
    const value = submitForm[field]?.trim()
    if (value) {
      values[field] = value
    }
  })
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Operator-Role': session.role,
      },
      body: JSON.stringify({ values }),
    })
    if (response.status === 403) {
      const payload = (await response.json().catch(() => ({}))) as { detail?: string }
      throw new Error(payload.detail ?? '只读岗位无权调整检查井归属')
    }
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '检查井上报未生效')
    }
    submitOpen.value = false
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查井上报失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json().catch(() => ({}))) as { ok: boolean; message: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '检查井动作未生效，请稍后重试')
    }
    await refreshAll()
    detail.value = null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查井操作失败'
  }
}

async function refreshAll() {
  await Promise.all([reload(), reloadStats(), reloadUrgings()])
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) {
    query.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  if (onlyKey.value) {
    query.set('only_key', '1')
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('检查井列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查井列表读取失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      stats.value = (await response.json()) as Stats
    }
  } catch {
    // 统计拉取失败不阻塞列表，页脚会提示筛选口径
  }
}

async function reloadUrgings() {
  try {
    const response = await request(`${ENDPOINT}/urgings`)
    if (response.ok) {
      const payload = (await response.json()) as { items: Urging[] }
      urgings.value = payload.items ?? []
    }
  } catch {
    urgings.value = []
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.filter-check {
  flex-direction: row;
  align-items: center;
  gap: 6px;
}

.tag {
  display: inline-block;
  padding: 0 6px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 18px;
}

.tag-key {
  color: #b45309;
  background: #fef3c7;
}

.urging-panel {
  margin-top: 12px;
  padding: 12px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fffbeb;
}

.urging-panel h3 {
  margin: 0 0 8px;
  font-size: 15px;
}

.urging-panel ul {
  margin: 0;
  padding-left: 18px;
}

.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0.45);
}

.modal {
  width: min(720px, 92vw);
  max-height: 84vh;
  overflow: auto;
  padding: 20px 24px;
  border-radius: 10px;
  background: #fff;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.detail-grid {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 6px 12px;
  margin: 12px 0;
}

.detail-grid dt {
  color: #6b7280;
}

.detail-grid dd {
  margin: 0;
}

.history-list {
  margin: 8px 0;
  padding-left: 18px;
}

.history-time {
  margin-right: 8px;
  color: #6b7280;
  font-size: 12px;
}

.submit-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
  margin-top: 12px;
}

.submit-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}

.submit-actions {
  grid-column: 1 / -1;
  display: flex;
  gap: 8px;
}
</style>
