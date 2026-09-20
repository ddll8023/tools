/** 在可终止 Worker 中解析 Markdown、代码和公式，避免复杂文档阻塞页面。 */
import { Marked } from 'marked'
import hljs from 'highlight.js'
import { initFormulaEngine, requireFormula } from '@/utils/math/engine'
import type { PreparedMarkdown, RenderedMarkdown } from './types'

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

/** 扫描未转义的结束符，避免跨行吞掉普通金额或在代码中预处理公式。 */
function inlineFormula(source: string): { raw: string; text: string } | undefined {
  if (!source.startsWith('$') || source.startsWith('$$') || /\s/.test(source[1] ?? ' ')) return
  for (let index = 1; index < source.length; index++) {
    if (source[index] === '\n') return
    if (source[index] === '\\') { index++; continue }
    if (source[index] !== '$') continue
    if (/\s/.test(source[index - 1]) || /\d/.test(source[index + 1] ?? '')) return
    return { raw: source.slice(0, index + 1), text: source.slice(1, index) }
  }
}

async function renderDocument(source: PreparedMarkdown): Promise<RenderedMarkdown> {
  await initFormulaEngine()
  const warnings = new Set<string>()
  let formulaCount = 0
  let embeddedSize = 0
  const reserveEmbeddedContent = (size: number) => {
    embeddedSize += size
    if (embeddedSize > 768 * 1024 * 1024) throw new Error('图片与公式展开后超过 768MB，请拆分文档')
  }
  const formula = (content: string, display: boolean): string => {
    if (++formulaCount > 1000) throw new Error('公式超过 1000 个，请拆分文档')
    try {
      const paths = requireFormula(content, display)
      reserveEmbeddedContent(paths.body.length)
      const height = paths.ascent + paths.descent
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(content)}" viewBox="${paths.viewBox}" width="${paths.width}em" height="${height}em" style="vertical-align:-${paths.descent}em"><title>${escapeHtml(content)}</title>${paths.body}</svg>`
      return display ? `<div class="math-block">${svg}</div>\n` : `<span class="math-inline">${svg}</span>`
    } catch (error: unknown) {
      if (embeddedSize > 768 * 1024 * 1024) throw error
      warnings.add('部分数学公式无法渲染，已保留原文，请在预览中检查')
      return `<code class="math-error">${escapeHtml(display ? `$$${content}$$` : `$${content}$`)}</code>`
    }
  }
  const markdown = new Marked({
    gfm: true,
    breaks: false,
    async: false,
    extensions: [
      {
        name: 'mathBlock',
        level: 'block',
        start: (source) => source.match(/^ {0,3}\$\$/m)?.index,
        tokenizer(source) {
          const match = /^ {0,3}\$\$([^\n]+?)\$\$[ \t]*(?:\n|$)/.exec(source)
            ?? /^ {0,3}\$\$[ \t]*\n([\s\S]+?)\n {0,3}\$\$[ \t]*(?:\n|$)/.exec(source)
          if (match) return { type: 'mathBlock', raw: match[0], text: match[1].trim() }
        },
        renderer(token) { return formula(String(token.text), true) },
      },
      {
        name: 'mathInline',
        level: 'inline',
        start: (source) => source.indexOf('$'),
        tokenizer(source) {
          const match = inlineFormula(source)
          if (match) return { type: 'mathInline', ...match }
        },
        renderer(token) { return formula(String(token.text), false) },
      },
    ],
    renderer: {
      html({ text }) {
        warnings.add('原始 HTML 已作为文本显示，不执行其中的标签或样式')
        return escapeHtml(text)
      },
      image({ href, text }) {
        let image = Object.prototype.hasOwnProperty.call(source.images, href) ? source.images[href] : undefined
        if (!image) {
          try {
            const normalized = encodeURI(decodeURI(href))
            image = Object.prototype.hasOwnProperty.call(source.images, normalized) ? source.images[normalized] : undefined
          } catch { /* 非法 URL 回退为图片占位文字。 */ }
        }
        if (!image || !/^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(image)) {
          warnings.add('存在未嵌入的图片，已显示替代文字；网络图片不会下载')
          return `<span class="missing-image">[图片未嵌入：${escapeHtml(text || '无替代文字')}]</span>`
        }
        // 同一资源被重复引用也计入展开预算，避免拼接后才发现 HTML 超大。
        reserveEmbeddedContent(image.length)
        return `<img src="${image}" alt="${escapeHtml(text)}" />`
      },
      link({ href, tokens }) {
        const label = this.parser.parseInline(tokens)
        if (!/^(https?:\/\/|mailto:|#)/i.test(href)) {
          warnings.add('非 HTTP、邮件或页内链接已转为普通文字')
          return label
        }
        return `<a href="${escapeHtml(href)}" rel="noreferrer">${label}</a>`
      },
      code({ text, lang }) {
        const language = (lang || '').split(/\s+/)[0]
        let code = escapeHtml(text)
        if (text.length <= 100_000 && language && hljs.getLanguage(language)) {
          try { code = hljs.highlight(text, { language, ignoreIllegals: true }).value } catch {
            warnings.add('部分代码未能高亮，已保留原文')
          }
        }
        return `<pre><code class="hljs">${code}</code></pre>\n`
      },
      checkbox({ checked }) { return checked ? '☑ ' : '☐ ' },
    },
  })
  const html = markdown.parse(source.markdown_content, { async: false })
  if (html.length > 1024 * 1024 * 1024) throw new Error('渲染内容过大，请减少图片或拆分文档')
  return { html, warnings: [...warnings] }
}

self.onmessage = async (event: MessageEvent<PreparedMarkdown>) => {
  try {
    const result = await renderDocument(event.data)
    self.postMessage({ ok: true, result })
  } catch (error: unknown) {
    self.postMessage({ ok: false, message: error instanceof Error ? error.message : '文档渲染失败' })
  }
}
