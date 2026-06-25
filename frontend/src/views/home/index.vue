/**
 * 首页
 * 功能描述：以网格卡片形式展示所有可用工具
 * 依赖组件：无
 */
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { toolConfigs } from '@/router/tools'

const router = useRouter()

function navigateTo(tool: { path: string; available?: boolean }) {
  if (tool.available === false) return
  router.push('/tools/' + tool.path)
}
</script>

<template>
  <div class="py-10">
    <header class="mb-10 text-center">
      <div
        class="mb-3.5 inline-flex h-[52px] w-[52px] items-center justify-center rounded-xl bg-primary-light"
      >
        <font-awesome-icon
          :icon="['fas', 'cube']"
          class="text-2xl text-primary-dark"
        />
      </div>
      <h1 class="mb-1.5 text-[26px] font-bold tracking-[-0.3px]">工具盒子</h1>
      <p class="text-[14px] text-text-secondary">
        轻量文档处理工具集，所有操作在本地完成
      </p>
    </header>

    <template v-if="toolConfigs.length > 0">
      <section
        class="mx-auto grid max-w-[900px] grid-cols-3 gap-5 px-8 justify-items-center"
      >
        <article
          v-for="tool in toolConfigs"
          :key="tool.id"
          class="flex w-full flex-col rounded-2xl border border-border bg-surface p-7 pb-6 transition-all duration-250"
          :class="tool.available === false
            ? 'cursor-default opacity-50 grayscale'
            : 'cursor-pointer hover:-translate-y-[3px] hover:border-transparent hover:shadow-lg active:translate-y-0 active:shadow-sm'"
          @click="navigateTo(tool)"
        >
          <div
            class="mb-4 flex h-11 w-11 items-center justify-center rounded-lg bg-primary-light text-xl text-primary-dark"
          >
            <font-awesome-icon :icon="tool.icon" />
          </div>
          <h3 class="mb-1.5 text-[16px] font-semibold">
            {{ tool.displayName }}
          </h3>
          <p class="mb-4 text-[13px] leading-relaxed text-text-secondary">
            {{ tool.description }}
          </p>
          <div class="mt-auto flex items-center justify-between">
            <span
              v-if="tool.available !== false"
              class="rounded-full bg-[#F0F5E9] px-2.5 py-0.5 text-[11px] font-medium text-[#4A8B2F]"
            >
              已就绪
            </span>
            <span
              v-else
              class="rounded-full bg-[#FFF0E0] px-2.5 py-0.5 text-[11px] font-medium text-[#B8860B]"
            >
              需安装 LibreOffice
            </span>
            <span
              class="text-sm text-text-tertiary transition-all duration-200"
            >
              <font-awesome-icon :icon="['fas', 'arrow-right']" />
            </span>
          </div>
        </article>
      </section>
    </template>
    <div v-else class="py-16 text-center">
      <p class="text-sm text-text-tertiary">暂无可用工具，敬请期待</p>
    </div>

    <footer class="mt-10 text-center text-[12px] text-text-tertiary">
      <span class="mx-3 inline-block">
        <font-awesome-icon :icon="['far', 'clock']" class="mr-1" />
        本地处理，文件不会上传
      </span>
      <span class="mx-3 inline-block">
        <font-awesome-icon :icon="['far', 'file-lines']" class="mr-1" />
        v0.1.0
      </span>
    </footer>
  </div>
</template>
