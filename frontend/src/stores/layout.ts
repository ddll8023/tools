import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useLayoutStore = defineStore('layout', () => {
  const sidebarCollapsed = ref(true)

  const toggleSidebar = () => {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  const setSidebarCollapsed = (value: boolean) => {
    sidebarCollapsed.value = value
  }

  return { sidebarCollapsed, toggleSidebar, setSidebarCollapsed }
})
