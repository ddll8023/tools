import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { library } from '@fortawesome/fontawesome-svg-core'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

import {
  faBars, faCube, faFilePdf, faFileWord, faImage,
  faCode, faPlus, faArrowRight,
  faUpload, faDownload, faRotate, faMagnifyingGlass,
  faSpinner, faTable, faArrowLeft,
  faWindowMinimize, faWindowMaximize, faWindowRestore, faXmark,
  faSliders, faWandMagicSparkles, faCheckCircle, faFileZipper, faBook,
  faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'

import {
  faFileLines, faClock, faFile, faCircleCheck,
  faCircleXmark, faHourglassHalf,
  faCopy, faImage as faImageRegular, faFileImage,
} from '@fortawesome/free-regular-svg-icons'

library.add(
  faBars, faCube, faFilePdf, faFileWord, faImage,
  faCode, faPlus, faArrowRight,
  faUpload, faDownload, faRotate, faMagnifyingGlass,
  faFileLines, faClock, faFile, faCircleCheck,
  faCircleXmark, faHourglassHalf,
  faCopy, faTable, faImageRegular, faSpinner, faArrowLeft,
  faWindowMinimize, faWindowMaximize, faWindowRestore, faXmark,
  faSliders, faWandMagicSparkles, faCheckCircle, faFileZipper, faBook,
  faTriangleExclamation, faFileImage,
)

import '@/style.css'
import App from '@/App.vue'
import { createAppRouter } from '@/router'

async function bootstrap() {
  const app = createApp(App)
  app.use(createPinia())

  const router = await createAppRouter()
  app.use(router)

  app.component('font-awesome-icon', FontAwesomeIcon)
  app.mount('#app')
}

bootstrap()
