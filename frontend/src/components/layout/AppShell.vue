/**
 * AppShell
 * 功能描述：全局布局组件，包含顶部栏 + 侧边栏 + 内容区
 * 依赖组件：AppSidebar
 */
<script setup lang="ts">
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { useLayoutStore } from '@/stores/layout'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const route = useRoute()
const layoutStore = useLayoutStore()

watch(
  () => route.meta.sidebarDefaultCollapsed,
  (val) => {
    layoutStore.setSidebarCollapsed(val !== false)
  },
  { immediate: true }
)
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-bg">
    <header
      class="relative z-30 flex h-[52px] flex-shrink-0 items-center border-b border-border bg-surface px-4"
    >
      <button
        class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border-none cursor-pointer text-lg text-text-secondary transition-all duration-200 hover:bg-hover hover:text-text"
        @click="layoutStore.toggleSidebar()"
        aria-label="切换侧边栏"
      >
        <font-awesome-icon :icon="['fas', 'bars']" />
      </button>

      <span class="ml-2.5 flex-shrink-0 text-[15px] font-semibold">工具盒子</span>

      <span
        v-if="route.meta.title && route.path !== '/'"
        class="absolute left-1/2 -translate-x-1/2 text-[13px] font-medium text-text-secondary"
      >
        {{ route.meta.title }}
      </span>

      <div
        class="ml-auto flex h-8 w-[180px] items-center rounded-full border border-border bg-bg px-3 transition-all duration-200 focus-within:w-[220px] focus-within:border-primary focus-within:bg-surface"
      >
        <font-awesome-icon
          :icon="['fas', 'magnifying-glass']"
          class="flex-shrink-0 text-[13px] text-text-tertiary"
        />
        <input
          type="text"
          placeholder="搜索工具..."
          readonly
          class="w-full border-none bg-transparent px-2 font-inherit text-[13px] text-text outline-none placeholder:text-text-tertiary"
        />
      </div>
    </header>

    <div class="flex flex-1 overflow-hidden">
      <AppSidebar />

      <main class="flex-1 overflow-y-auto">
        <router-view />
      </main>
    </div>
  </div>
</template>
