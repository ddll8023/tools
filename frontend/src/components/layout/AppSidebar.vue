/**
 * AppSidebar
 * 功能描述：可收起侧边栏，展示工具导航列表
 * 依赖组件：无
 */
<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useLayoutStore } from '@/stores/layout'
import { toolConfigs } from '@/router/tools'

const router = useRouter()
const route = useRoute()
const layoutStore = useLayoutStore()

function navigateTo(path: string) {
  router.push(path)
}

function canNavigate(tool: { available?: boolean }): boolean {
  return tool.available !== false
}
</script>

<template>
  <aside
    class="flex-shrink-0 z-20 w-[220px] overflow-y-auto border-r border-border bg-surface py-3 px-2.5 transition-all duration-250 ease"
    :class="layoutStore.sidebarCollapsed ? '-ml-[220px] opacity-0 pointer-events-none' : 'ml-0 opacity-100'"
  >
    <div
      class="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.8px] text-text-tertiary"
    >
      工具列表
    </div>

    <a
      class="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium no-underline cursor-pointer transition-all duration-150 hover:bg-hover hover:text-text"
      :class="{ '!bg-primary-light !text-primary-dark': route.path === '/' }"
      @click="navigateTo('/')"
    >
      <span class="flex-shrink-0 w-6 text-center text-[15px]">
        <font-awesome-icon :icon="['fas', 'cube']" />
      </span>
      <span>首页</span>
    </a>

    <div class="mx-3 my-2 h-px bg-border"></div>

    <template v-if="toolConfigs.length > 0">
      <a
        v-for="tool in toolConfigs"
        :key="tool.id"
        class="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium no-underline transition-all duration-150"
        :class="!canNavigate(tool)
          ? 'cursor-default text-text-tertiary'
          : 'cursor-pointer hover:bg-hover hover:text-text ' + (route.path === '/tools/' + tool.path ? '!bg-primary-light !text-primary-dark' : '')"
        @click="canNavigate(tool) && navigateTo('/tools/' + tool.path)"
      >
        <span class="flex-shrink-0 w-6 text-center text-[15px]">
          <font-awesome-icon :icon="tool.icon" />
        </span>
        <span>{{ tool.displayName }}</span>
      </a>
    </template>
    <p v-else class="px-3 py-4 text-center text-xs text-text-tertiary">
      暂无可用工具
    </p>
  </aside>
</template>
