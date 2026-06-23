/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

import type { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

declare module 'vue' {
  interface GlobalComponents {
    'font-awesome-icon': typeof FontAwesomeIcon
  }
}

export {}
