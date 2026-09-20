/** 使用本地 MathJax 将公式转换成不含外部资源的独立 SVG 路径。 */
import { mathjax } from '@mathjax/src/mjs/mathjax.js'
import { TeX } from '@mathjax/src/mjs/input/tex.js'
import { SVG } from '@mathjax/src/mjs/output/svg.js'
import { liteAdaptor } from '@mathjax/src/mjs/adaptors/liteAdaptor.js'
import { LiteElement } from '@mathjax/src/mjs/adaptors/lite/Element.js'
import { RegisterHTMLHandler } from '@mathjax/src/mjs/handlers/html.js'
import { MathJaxTexFont } from '@mathjax/mathjax-tex-font/mjs/svg.js'
import '@mathjax/src/mjs/input/tex/ams/AmsConfiguration.js'
import '@mathjax/src/mjs/input/tex/newcommand/NewcommandConfiguration.js'
import '@mathjax/src/mjs/input/tex/boldsymbol/BoldsymbolConfiguration.js'

const adaptor = liteAdaptor()
RegisterHTMLHandler(adaptor)
const createDocument = () => mathjax.document('', {
  InputJax: new TeX({
    // 不启用 require/autoload/html，阻止用户公式联网或注入 HTML；宏定义按次隔离。
    packages: ['base', 'ams', 'newcommand', 'boldsymbol'],
    maxBuffer: 16 * 1024,
    formatError: (_jax: unknown, error: Error) => { throw error },
  }),
  OutputJax: new SVG({
    fontData: MathJaxTexFont,
    fontCache: 'none',
    linebreaks: { inline: false },
    displayOverflow: 'overflow',
  }),
  compileError: (_document: unknown, _math: unknown, error: Error) => { throw error },
})

/** 返回独立 SVG 路径及每 em 对应 1000 单位的几何信息。 */
export function renderFormulaPaths(content: string, display: boolean) {
  const document = createDocument()
  const container = document.convert(content, { display })
  const svg = adaptor.firstChild(container)
  if (!(svg instanceof LiteElement) || adaptor.kind(svg) !== 'svg') throw new Error('Formula did not produce SVG')
  const viewBox: number[] | undefined = adaptor.getAttribute(svg, 'viewBox')?.split(/\s+/).map(Number)
  if (!viewBox || viewBox.length !== 4 || viewBox.some((v) => !Number.isFinite(v))) {
    throw new Error('Invalid formula dimensions')
  }
  const [x, y, width, height] = viewBox
  // data-latex 中的比较符可能破坏 SVG XML 序列化；元数据不参与渲染，统一移除。
  removeMathJaxSourceAttributes(svg)
  const body = adaptor.innerHTML(svg)
  if (/<(?:foreignObject|script|image)\b|(?:href|xlink:href)=/i.test(body)) {
    throw new Error('Formula contains unsupported external content')
  }
  // 为根号和横线留出边距，避免栅格化时边缘裁切。
  const padding = 40
  return {
    body,
    viewBox: `${x - padding} ${y - padding} ${width + padding * 2} ${height + padding * 2}`,
    width: (width + padding * 2) / 1000,
    ascent: (-y + padding) / 1000,
    descent: (y + height + padding) / 1000,
  }
}

function removeMathJaxSourceAttributes(node: LiteElement): void {
  if (adaptor.hasAttribute(node, 'data-latex')) adaptor.removeAttribute(node, 'data-latex')
  for (const child of adaptor.childNodes(node)) {
    if (child instanceof LiteElement) removeMathJaxSourceAttributes(child)
  }
}
