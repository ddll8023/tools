import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { initToolConfigs, generateToolRoutes } from '@/router/tools'

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

  return createRouter({
    history: createWebHashHistory(),
    routes,
  })
}
