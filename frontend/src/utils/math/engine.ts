/** 离线 MathJax 公式引擎：共享初始化、有限缓存和纯 SVG 路径，不包含业务布局。 */
export interface FormulaPaths {
  body: string
  viewBox: string
  width: number
  ascent: number
  descent: number
}

type Renderer = (content: string, display: boolean) => FormulaPaths
let renderer: Renderer | undefined
let loading: Promise<void> | undefined
let revision = 0
const listeners = new Set<() => void>()
const cache = new Map<string, FormulaPaths | Error>()
const CACHE_LIMIT = 512

export const getFormulaRevision = () => revision
export const subscribeFormulaEngine = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 只加载应用内模块与字形路径，不访问 CDN 或远程字体。 */
export function initFormulaEngine(): Promise<void> {
  if (!loading) {
    loading = import('./mathjax-renderer').then((module) => {
      renderer = module.renderFormulaPaths
      revision++
      for (const listener of listeners) listener()
    }).catch((error: unknown) => {
      loading = undefined
      throw error
    })
  }
  return loading
}

export function requireFormula(content: string, display: boolean): FormulaPaths {
  if (!renderer) throw new Error('数学渲染器尚未就绪，请稍后再导出。')
  const key = JSON.stringify([display, content])
  let result = cache.get(key)
  if (!result) {
    try {
      result = renderer(content, display)
    } catch {
      result = new Error(`公式无法渲染：${content.slice(0, 100)}`)
    }
    if (cache.size >= CACHE_LIMIT) {
      const oldest = cache.keys().next().value
      if (oldest !== undefined) cache.delete(oldest)
    }
    cache.set(key, result)
  }
  if (result instanceof Error) throw result
  return result
}
