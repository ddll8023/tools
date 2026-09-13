export function getBoundaryOffset(el: HTMLElement, container: Node, offset: number): number {
  let total = 0
  const children = el.childNodes

  for (let i = 0; i < children.length; i++) {
    const child = children[i]
    if (container === el && offset <= i) return total

    if (container === child || child.contains(container)) {
      const range = document.createRange()
      range.selectNodeContents(child)
      range.setEnd(container, offset)
      return total + range.toString().length
    }

    total += (child.textContent || '').length
    if (i < children.length - 1) total += 1
  }

  return total
}

export function saveCaret(el: HTMLElement): number {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return 0

  const range = selection.getRangeAt(0)
  return getBoundaryOffset(el, range.startContainer, range.startOffset)
}

export function getSelectionOffsets(el: HTMLElement): { start: number; end: number } {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) {
    const offset = saveCaret(el)
    return { start: offset, end: offset }
  }

  const range = selection.getRangeAt(0)
  const isInsideEditor = (node: Node) => node === el || el.contains(node)
  if (!isInsideEditor(range.startContainer) || !isInsideEditor(range.endContainer)) {
    const offset = saveCaret(el)
    return { start: offset, end: offset }
  }

  const start = getBoundaryOffset(el, range.startContainer, range.startOffset)
  const end = getBoundaryOffset(el, range.endContainer, range.endOffset)
  return start <= end ? { start, end } : { start: end, end: start }
}

export function restoreCaret(el: HTMLElement, offset: number): void {
  const selection = window.getSelection()
  if (!selection) return

  let remaining = offset
  const children = el.childNodes

  for (let i = 0; i < children.length; i++) {
    const child = children[i]
    const lineLength = (child.textContent || '').length

    if (remaining <= lineLength) {
      const range = document.createRange()
      let found = false

      const walk = (node: Node): boolean => {
        if (node.nodeType === Node.TEXT_NODE) {
          const length = node.textContent?.length ?? 0
          if (remaining <= length) {
            range.setStart(node, remaining)
            range.collapse(true)
            found = true
            return true
          }
          remaining -= length
        } else {
          for (let index = 0; index < node.childNodes.length; index++) {
            if (walk(node.childNodes[index])) return true
          }
        }
        return false
      }
      walk(child)

      if (!found) {
        range.setStart(child, 0)
        range.collapse(true)
      }
      selection.removeAllRanges()
      selection.addRange(range)
      return
    }

    remaining -= lineLength + 1
  }

  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
}

export function getPlainText(el: HTMLElement): string {
  const children = el.childNodes
  if (children.length === 0) return ''

  const lines: string[] = []
  for (let index = 0; index < children.length; index++) {
    lines.push(children[index].textContent || '')
  }
  return lines.join('\n').replace(/\u00a0/g, ' ')
}
