/**
 * PDF 转 Markdown 工具页
 * 功能描述：上传 PDF → 转换 → 预览 → 下载，全流程 UI 骨架
 * 依赖组件：无
 */
<script setup lang="ts">
import { ref } from 'vue'

const currentState = ref<'upload' | 'progress' | 'result' | 'error'>('upload')

const stateLabels: Record<string, string> = {
  upload: '上传状态',
  progress: '转换中',
  result: '结果展示',
  error: '错误状态'
}

const stateList = ['upload', 'progress', 'result', 'error'] as const

function setState(state: typeof currentState.value) {
  currentState.value = state
}
</script>

<template>
  <main class="mx-auto w-full max-w-[860px] py-7">
    <!-- 演示控制 -->
    <div class="mb-5 flex gap-2">
      <button
        v-for="state in stateList"
        :key="state"
        class="cursor-pointer rounded-full border border-border bg-surface px-3 py-1 font-inherit text-xs text-text-secondary transition-all duration-200 hover:border-primary hover:text-primary-dark"
        :class="{ '!border-primary !bg-primary-light !text-primary-dark': currentState === state }"
        @click="setState(state)"
      >
        {{ stateLabels[state] }}
      </button>
    </div>

    <!-- 上传 -->
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['far', 'file']" class="mr-1.5" />
        选择文件
      </div>

      <div
        class="cursor-pointer rounded-xl border-2 border-dashed border-border py-11 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
      >
        <div class="mb-3.5 text-[38px] text-text-tertiary">
          <font-awesome-icon :icon="['fas', 'file-pdf']" />
        </div>
        <h2 class="mb-1.5 text-[15px] font-semibold">
          将 PDF 文件拖拽到此处
        </h2>
        <p class="mb-[18px] text-[13px] text-text-secondary">
          或点击下方按钮选择文件
        </p>
        <button
          class="inline-flex items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white cursor-pointer transition-all duration-200 hover:bg-primary-dark"
        >
          <font-awesome-icon :icon="['fas', 'upload']" />
          选择 PDF 文件
        </button>
        <div class="mt-3.5 text-[12px] text-text-tertiary">
          支持 .pdf 格式，最大 50MB
        </div>
      </div>

      <!-- 文件已选 -->
      <div
        v-if="currentState !== 'upload'"
        class="mt-[18px] flex items-center justify-center gap-3 rounded-lg bg-[#F9F9F6] px-5 py-3 text-[13px]"
      >
        <font-awesome-icon
          :icon="['far', 'circle-check']"
          class="text-success"
        />
        <span class="font-medium">2024年度报告.pdf</span>
        <span class="text-text-secondary">(2.4 MB)</span>
        <span
          class="ml-auto cursor-pointer p-1 text-text-tertiary hover:text-error"
        >
          <font-awesome-icon :icon="['far', 'circle-xmark']" />
        </span>
      </div>
    </section>

    <!-- 进度 -->
    <section
      v-if="currentState === 'progress'"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['far', 'hourglass-half']" class="mr-1.5" />
        转换中
      </div>

      <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]">
        <div
          class="h-full w-[65%] rounded-full bg-primary transition-all duration-400"
        ></div>
      </div>

      <div class="flex flex-col gap-2.5 text-[13px]">
        <div class="flex items-center gap-2.5 text-success">
          <span class="w-5 text-center text-sm">
            <font-awesome-icon :icon="['far', 'circle-check']" />
          </span>
          读取 PDF 文件
        </div>
        <div class="flex items-center gap-2.5 text-success">
          <span class="w-5 text-center text-sm">
            <font-awesome-icon :icon="['far', 'circle-check']" />
          </span>
          提取文本内容
        </div>
        <div class="flex items-center gap-2.5 text-success">
          <span class="w-5 text-center text-sm">
            <font-awesome-icon :icon="['far', 'circle-check']" />
          </span>
          提取表格
        </div>
        <div class="flex items-center gap-2.5 font-medium">
          <span class="w-5 text-center text-sm text-primary">
            <font-awesome-icon :icon="['fas', 'spinner']" spin />
          </span>
          生成 Markdown
        </div>
      </div>
    </section>

    <!-- 结果 -->
    <section
      v-if="currentState === 'result'"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['far', 'file-lines']" class="mr-1.5" />
        转换结果
      </div>

      <div class="mb-[18px] flex flex-wrap gap-2.5">
        <button
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark"
        >
          <font-awesome-icon :icon="['fas', 'download']" />
          下载 .md
        </button>
        <button
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
        >
          <font-awesome-icon :icon="['far', 'copy']" />
          复制内容
        </button>
        <button
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
        >
          <font-awesome-icon :icon="['fas', 'rotate']" />
          重新上传
        </button>
      </div>

      <div
        class="mb-3 flex items-center justify-between text-[12px] text-text-secondary"
      >
        <div>
          <span class="mr-4">
            <font-awesome-icon :icon="['far', 'file']" class="mr-1" />12 页
          </span>
          <span class="mr-4">
            <font-awesome-icon :icon="['fas', 'table']" class="mr-1" />3 个表格
          </span>
          <span>
            <font-awesome-icon :icon="['far', 'image']" class="mr-1" />2 张图片
          </span>
        </div>
      </div>

      <div
        class="max-h-[420px] overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-[#F7F7F4] p-6 font-mono text-[13px] leading-relaxed text-[#3A3A3A]"
      >
<h1 class="mb-2 mt-4 block text-lg font-bold text-text">2024 年度工作总结</h1>

<h2 class="mb-1.5 mt-3 block text-[15px] font-semibold text-text">一、业务概况</h2>

<p>2024 年公司整体业务保持稳定增长，全年营收达到 <strong>1,280 万元</strong>，同比增长 18.6%。</p>

<h2 class="mb-1.5 mt-3 block text-[15px] font-semibold text-text">二、核心数据</h2>

| 季度 | 营收（万元） | 同比增长 |
|------|-------------|---------|
| Q1   | 280         | +12.3%  |
| Q2   | 315         | +15.7%  |
| Q3   | 340         | +20.4%  |
| Q4   | 345         | +25.1%  |

<em class="my-3 block text-text-secondary">[图片: 营收趋势图]</em>

<h2 class="mb-1.5 mt-3 block text-[15px] font-semibold text-text">三、重点项目</h2>

<h3 class="mb-1 mt-2 text-[14px] font-semibold">3.1 平台升级</h3>

<p>已完成核心系统从 v2 到 v3 的迁移。</p>
      </div>
    </section>

    <!-- 错误 -->
    <section
      v-if="currentState === 'error'"
      class="mt-4 flex items-start gap-3 rounded-lg border border-[#FFD7D7] bg-[#FFF5F5] p-4 pl-5"
    >
      <font-awesome-icon
        :icon="['far', 'circle-xmark']"
        class="mt-0.5 text-lg text-error"
      />
      <div>
        <h4 class="mb-1 text-[14px] font-semibold">转换失败</h4>
        <p class="text-[13px] text-text-secondary">
          该 PDF 文件包含加密内容，无法解析。请确认文件未设置密码保护。
        </p>
      </div>
    </section>

    <footer class="mt-5 text-center text-[12px] text-text-tertiary">
      <font-awesome-icon :icon="['far', 'clock']" class="mr-1" />
      本地处理，文件不会上传
    </footer>
  </main>
</template>
