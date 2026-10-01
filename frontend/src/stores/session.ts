import { defineStore } from 'pinia'

// 只读岗位：后端会拒绝其归属调整等写操作，前端也直接隐藏对应入口
export const READONLY_ROLES = ['只读员', 'viewer', 'readonly']

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '城市地下管网巡检养护平台',
    role: '值班管理员',
    roleOptions: ['值班管理员', '巡检员', '只读员'],
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    readonly: (state) => READONLY_ROLES.includes(state.role),
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setRole(role: string) {
      this.role = role
    },
  },
})
