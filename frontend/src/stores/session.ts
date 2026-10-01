import { defineStore } from 'pinia'

export type Role = 'admin' | 'operator' | 'editor' | 'viewer'

export const ROLE_OPTIONS: { value: Role; label: string; readonly: boolean }[] = [
  { value: 'admin', label: '管理员', readonly: false },
  { value: 'operator', label: '值班操作员', readonly: false },
  { value: 'editor', label: '维护人员', readonly: false },
  { value: 'viewer', label: '只读查看员', readonly: true },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    role: 'operator' as Role,
    shiftLabel: '白班 08:00-20:00',
    scope: '城市地下管网巡检养护平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isReadonly: (state) => ROLE_OPTIONS.find((item) => item.value === state.role)?.readonly ?? false,
    roleLabel: (state) => ROLE_OPTIONS.find((item) => item.value === state.role)?.label ?? state.role,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setRole(role: Role) {
      this.role = role
    },
  },
})
