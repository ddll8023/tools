import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { initToolConfigs, generateToolRoutes, toolConfigs } from '@/router/tools'

export async function createAppRouter() {
  const configs = await initToolConfigs()

  const routes: RouteRecordRaw[] = [
    {
      path: '/',
      component: () => import('@/components/layout/AppShell.vue'),
      children: [
        {
          path: '',
          name: 'Home',
          component: () => import('@/views/home/index.vue'),
          meta: {
            title: '工具盒子',
            sidebarDefaultCollapsed: true,
          },
        },
        {
          path: 'tools',
          children: generateToolRoutes(configs),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      component: () => import('@/views/error/404.vue'),
    },
  ]

  const router = createRouter({
    history: createWebHashHistory(),
    routes,
  })

  // 不可用工具（如缺少 LibreOffice 的 Word 转 PDF）禁止直接进入，重定向首页
  router.beforeEach((to) => {
    const toolId = to.meta.id as string | undefined
    if (toolId) {
      const tool = toolConfigs.value.find((t) => t.id === toolId)
      if (tool && tool.available === false) {
        return { path: '/' }
      }
    }
    return true
  })

  return router
}
