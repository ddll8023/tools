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
    // Deliberately exclude require/autoload/html: user formulas cannot fetch resources
    // or inject links/HTML. Each conversion gets its own macro definitions.
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

/** A self-contained SVG in MathJax's 1000-units-per-em coordinates. */
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
  // MathJax keeps the original TeX in data-latex attributes. Its lite
  // serializer can emit raw `<`/`>` from TeX comparisons, which is tolerated
  // by the live HTML preview but makes the SVG invalid when loaded as an image
  // for PNG export. These attributes are metadata only and are not needed for
  // rendering, so remove them before embedding the paths.
  removeMathJaxSourceAttributes(svg)
  const body = adaptor.innerHTML(svg)
  if (/<(?:foreignObject|script|image)\b|(?:href|xlink:href)=/i.test(body)) {
    throw new Error('Formula contains unsupported external content')
  }
  // Small ink padding prevents radical/bar edge clipping during PNG rasterization.
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
