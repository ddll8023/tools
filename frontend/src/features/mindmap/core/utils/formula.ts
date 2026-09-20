/** 思维导图公式尺寸与 SVG 定位；渲染引擎与 Markdown PDF 共用。 */
import { requireFormula } from '../../../../utils/math/engine'
import type { FormulaPaths } from '../../../../utils/math/engine'
export { initFormulaEngine, requireFormula, getFormulaRevision, subscribeFormulaEngine } from '../../../../utils/math/engine'
export type { FormulaPaths } from '../../../../utils/math/engine'

export interface FormulaMetrics extends FormulaPaths {
  height: number
}

/** 引擎尚未就绪或输入不完整时，预览回退到可见源码。 */
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

/** 思维导图预览与导出共用 SVG 标记；baseline 为文本基线坐标。 */
export function buildFormulaSvg(formula: FormulaMetrics, x: number, baseline: number, color: string, label: string): string {
  return `<svg class="mindmap-formula" xmlns="http://www.w3.org/2000/svg" x="${x}" y="${baseline - formula.ascent}" width="${formula.width}" height="${formula.height}" viewBox="${formula.viewBox}" color="${escapeXml(color)}" role="img"><title>${escapeXml(label)}</title>${formula.body}</svg>`
}
