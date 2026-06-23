/**
 * 404 页面
 * 功能描述：路由未匹配时的兜底页面
 */
<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <main class="flex min-h-full flex-col items-center justify-center py-20">
    <div
      class="mb-5 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-primary-light"
    >
      <font-awesome-icon
        :icon="['fas', 'cube']"
        class="text-3xl text-primary-dark"
      />
    </div>
    <h1 class="mb-2 text-6xl font-bold text-text">404</h1>
    <p class="mb-8 text-base text-text-secondary">页面不存在</p>
    <button
      class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-6 py-2.5 font-inherit text-sm font-medium text-white transition-all duration-200 hover:bg-primary-dark"
      @click="router.push('/')"
    >
      <font-awesome-icon :icon="['fas', 'arrow-left']" />
      返回首页
    </button>
  </main>
</template>
