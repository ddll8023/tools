<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { highlightMindmapHTML } from '../core'
import {
  getPlainText,
  getSelectionOffsets,
  restoreCaret,
  saveCaret,
} from './editor-utils'

interface Props {
  modelValue: string
  readonly?: boolean
  className?: string
}

const props = withDefaults(defineProps<Props>(), {
  readonly: false,
  className: '',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  paste: [value: string]
}>()

const editorRef = ref<HTMLElement | null>(null)
const isInternalEdit = ref(false)
const lastExternalValue = ref(props.modelValue)
const isComposing = ref(false)
const undoStack = ref<{ text: string; caret: number }[]>([
  { text: props.modelValue, caret: 0 },
])
const redoStack = ref<{ text: string; caret: number }[]>([])
const lastUndoPush = ref(0)

function renderText(text: string, caret?: number) {
  const editor = editorRef.value
  if (!editor) return

  lastExternalValue.value = text
  editor.innerHTML = highlightMindmapHTML(text)
  if (caret !== undefined) restoreCaret(editor, caret)
}

function pushUndo(text: string, caret: number) {
  const now = Date.now()
  const stack = undoStack.value
  if (now - lastUndoPush.value < 300 && stack.length > 1) {
    stack[stack.length - 1] = { text, caret }
  } else {
    stack.push({ text, caret })
    if (stack.length > 100) stack.shift()
  }
  lastUndoPush.value = now
  redoStack.value = []
}

function updateText(text: string, caret?: number) {
  const editor = editorRef.value
  if (!editor) return

  isInternalEdit.value = true
  lastExternalValue.value = text
  editor.innerHTML = highlightMindmapHTML(text)
  if (caret !== undefined) restoreCaret(editor, caret)
  emit('update:modelValue', text)
}

function handleInput() {
  const editor = editorRef.value
  if (!editor || isComposing.value || props.readonly) return

  const caret = saveCaret(editor)
  const text = getPlainText(editor)
  editor.innerHTML = highlightMindmapHTML(text)
  restoreCaret(editor, caret)
  lastExternalValue.value = text
  isInternalEdit.value = true
  pushUndo(text, caret)
  emit('update:modelValue', text)
}

function handleUndo() {
  const stack = undoStack.value
  if (stack.length <= 1) return
  const previous = stack.pop()
  if (!previous) return
  redoStack.value.push(previous)
  isInternalEdit.value = true
  updateText(stack[stack.length - 1].text, stack[stack.length - 1].caret)
}

function handleRedo() {
  const entry = redoStack.value.pop()
  if (!entry) return
  undoStack.value.push(entry)
  isInternalEdit.value = true
  updateText(entry.text, entry.caret)
}

function handleKeydown(event: KeyboardEvent) {
  const editor = editorRef.value
  if (!editor || isComposing.value || props.readonly) return

  if ((event.metaKey || event.ctrlKey) && event.key === 'z' && !event.shiftKey) {
    event.preventDefault()
    handleUndo()
    return
  }

  if ((event.metaKey || event.ctrlKey) && ((event.key === 'z' && event.shiftKey) || event.key === 'y')) {
    event.preventDefault()
    handleRedo()
    return
  }

  if (event.key === 'Enter') {
    event.preventDefault()
    const caret = saveCaret(editor)
    const text = getPlainText(editor)
    const nextText = text.slice(0, caret) + '\n' + text.slice(caret)
    pushUndo(nextText, caret + 1)
    updateText(nextText, caret + 1)
    return
  }

  if (event.key !== 'Tab') return
  event.preventDefault()
  const caret = saveCaret(editor)
  const text = getPlainText(editor)

  if (event.shiftKey) {
    const lineStart = text.lastIndexOf('\n', caret - 1) + 1
    const lineText = text.slice(lineStart)
    const match = lineText.match(/^ {1,2}/)
    if (!match) return
    const removed = match[0].length
    const nextText = text.slice(0, lineStart) + lineText.slice(removed)
    const nextCaret = Math.max(lineStart, caret - removed)
    pushUndo(nextText, nextCaret)
    updateText(nextText, nextCaret)
    return
  }

  const nextText = text.slice(0, caret) + '  ' + text.slice(caret)
  pushUndo(nextText, caret + 2)
  updateText(nextText, caret + 2)
}

function handlePaste(event: ClipboardEvent) {
  if (props.readonly) return
  event.preventDefault()
  const pastedText = event.clipboardData?.getData('text/plain') ?? ''
  const editor = editorRef.value
  if (!editor) return

  const text = getPlainText(editor)
  const { start, end } = getSelectionOffsets(editor)
  const nextText = text.slice(0, start) + pastedText + text.slice(end)
  const nextCaret = start + pastedText.length
  pushUndo(nextText, nextCaret)
  updateText(nextText, nextCaret)
  if (pastedText) emit('paste', pastedText)
}

function handleCompositionStart() {
  isComposing.value = true
}

function handleCompositionEnd() {
  isComposing.value = false
  handleInput()
}

watch(() => props.modelValue, (value) => {
  const editor = editorRef.value
  if (!editor) return
  if (isInternalEdit.value) {
    isInternalEdit.value = false
    return
  }
  if (value === lastExternalValue.value && editor.innerHTML !== '') return

  renderText(value)
  undoStack.value = [{ text: value, caret: 0 }]
  redoStack.value = []
})

onMounted(async () => {
  await nextTick()
  renderText(props.modelValue)
})
</script>

<template>
  <pre
    ref="editorRef"
    class="mindmap-text-editor"
    :class="[className, { 'mindmap-text-editor-readonly': readonly }]"
    :contenteditable="!readonly"
    role="textbox"
    aria-label="Markdown 思维导图编辑器"
    spellcheck="false"
    @input="handleInput"
    @keydown="handleKeydown"
    @paste="handlePaste"
    @compositionstart="handleCompositionStart"
    @compositionend="handleCompositionEnd"
  ></pre>
</template>
