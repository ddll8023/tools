export interface FormulaPaths {
  body: string
  viewBox: string
  width: number
  ascent: number
  descent: number
}

export interface FormulaMetrics extends FormulaPaths {
  height: number
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

/** All JS and glyph paths are local; no CDN, DOM, CSS or font loading is needed. */
export function initFormulaEngine(): Promise<void> {
  if (!loading) {
    loading = import('./mathjax-renderer').then((module) => {
      renderer = module.renderFormulaPaths
      revision++
      for (const listener of listeners) listener()
    }).catch((error: unknown) => {
      loading = undefined // A failed chunk load may be retried on export.
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
    } catch (cause) {
      result = new Error(`公式无法渲染：${content.slice(0, 100)}`, { cause })
    }
    if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value!)
    cache.set(key, result)
  }
  if (result instanceof Error) throw result
  return result
}

/** Preview falls back to visible source while loading or when the input is incomplete. */
export function measureFormula(content: string, display: boolean, fontSize: number): FormulaMetrics | undefined {
  try {
    const paths = requireFormula(content, display)
    return {
      ...paths,
      width: paths.width * fontSize,
      ascent: paths.ascent * fontSize,
      descent: paths.descent * fontSize,
      height: (paths.ascent + paths.descent) * fontSize,
    }
  } catch {
    return undefined
  }
}

function escapeXml(value: string) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** Same SVG markup for React preview and both export formats. y is the SVG text baseline. */
export function buildFormulaSvg(formula: FormulaMetrics, x: number, baseline: number, color: string, label: string): string {
  return `<svg class="mindmap-formula" xmlns="http://www.w3.org/2000/svg" x="${x}" y="${baseline - formula.ascent}" width="${formula.width}" height="${formula.height}" viewBox="${formula.viewBox}" color="${escapeXml(color)}" role="img"><title>${escapeXml(label)}</title>${formula.body}</svg>`
}
