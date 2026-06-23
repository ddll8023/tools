import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { library } from '@fortawesome/fontawesome-svg-core'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

import {
  faBars, faCube, faFilePdf, faFileWord, faImage,
  faCode, faPlus, faArrowRight,
  faUpload, faDownload, faRotate, faMagnifyingGlass,
  faSpinner, faTable, faArrowLeft,
  faWindowMinimize, faWindowMaximize, faWindowRestore, faXmark
} from '@fortawesome/free-solid-svg-icons'

import {
  faFileLines, faClock, faFile, faCircleCheck,
  faCircleXmark, faHourglassHalf,
  faCopy, faImage as faImageRegular
} from '@fortawesome/free-regular-svg-icons'

library.add(
  faBars, faCube, faFilePdf, faFileWord, faImage,
  faCode, faPlus, faArrowRight,
  faUpload, faDownload, faRotate, faMagnifyingGlass,
  faFileLines, faClock, faFile, faCircleCheck,
  faCircleXmark, faHourglassHalf,
  faCopy, faTable, faImageRegular, faSpinner, faArrowLeft,
  faWindowMinimize, faWindowMaximize, faWindowRestore, faXmark
)

import '@/style.css'
import App from '@/App.vue'
import router from '@/router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.component('font-awesome-icon', FontAwesomeIcon)
app.mount('#app')
