<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useAttrs, watch } from 'vue'
import type { SelectOption } from './types'

defineOptions({ inheritAttrs: false })

let nextBaseSelectId = 0

interface Props {
  modelValue?: string
  options: SelectOption[]
  placeholder?: string
  size?: 'sm' | 'md'
  block?: boolean
  disabled?: boolean
  required?: boolean
  id?: string
  name?: string
  ariaLabel?: string
  ariaDescribedby?: string
  ariaInvalid?: boolean | 'true' | 'false'
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  placeholder: undefined,
  size: 'md',
  block: false,
  disabled: false,
  required: false,
  id: undefined,
  name: undefined,
  ariaLabel: undefined,
  ariaDescribedby: undefined,
  ariaInvalid: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: [value: string]
}>()

const attrs = useAttrs()
const generatedId = `base-select-${++nextBaseSelectId}`
const isOpen = ref(false)
const activeIndex = ref(-1)
const rootRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const optionRefs = ref<HTMLElement[]>([])

const rootAttrs = computed(() => ({
  class: attrs.class,
  style: attrs.style,
}))
const triggerAttrs = computed(() => {
  const { class: _class, style: _style, ...rest } = attrs
  return rest
})
const controlId = computed(() => props.id || generatedId)
const listboxId = computed(() => `${controlId.value}-listbox`)
const selectedOption = computed(() => props.options.find((option) => option.value === props.modelValue))
const displayLabel = computed(() => selectedOption.value?.label ?? props.placeholder ?? '')
const isPlaceholder = computed(() => !selectedOption.value && props.placeholder !== undefined)
const activeDescendant = computed(() => (
  isOpen.value && activeIndex.value >= 0
    ? `${listboxId.value}-option-${activeIndex.value}`
    : undefined
))

function isOptionEnabled(index: number): boolean {
  return Boolean(props.options[index] && !props.options[index].disabled)
}

function findFirstEnabled(): number {
  return props.options.findIndex((option) => !option.disabled)
}

function findLastEnabled(): number {
  for (let index = props.options.length - 1; index >= 0; index--) {
    if (isOptionEnabled(index)) return index
  }
  return -1
}

function syncActiveIndex() {
  const selectedIndex = props.options.findIndex((option) => (
    option.value === props.modelValue && !option.disabled
  ))
  activeIndex.value = selectedIndex >= 0 ? selectedIndex : findFirstEnabled()
}

function scrollActiveOption() {
  const option = optionRefs.value[activeIndex.value]
  option?.scrollIntoView({ block: 'nearest' })
}

function addDocumentListeners() {
  document.addEventListener('pointerdown', handleDocumentPointerDown, true)
  document.addEventListener('scroll', handleDocumentScroll, true)
  window.addEventListener('resize', handleWindowResize)
}

function removeDocumentListeners() {
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  document.removeEventListener('scroll', handleDocumentScroll, true)
  window.removeEventListener('resize', handleWindowResize)
}

function openMenu() {
  if (props.disabled || isOpen.value) return
  isOpen.value = true
  syncActiveIndex()
  void nextTick(scrollActiveOption)
}

function closeMenu(restoreFocus = false) {
  if (!isOpen.value) return
  isOpen.value = false
  activeIndex.value = -1
  if (restoreFocus) void nextTick(() => triggerRef.value?.focus())
}

function toggleMenu() {
  if (props.disabled) return
  if (isOpen.value) closeMenu()
  else openMenu()
}

function moveActive(delta: number) {
  const total = props.options.length
  if (total === 0) return

  let index = activeIndex.value
  if (index < 0) index = delta > 0 ? findFirstEnabled() : findLastEnabled()
  if (index < 0) return

  for (let step = 0; step < total; step++) {
    index = (index + delta + total) % total
    if (isOptionEnabled(index)) {
      activeIndex.value = index
      void nextTick(scrollActiveOption)
      return
    }
  }
}

function setActiveIndex(index: number) {
  if (!isOptionEnabled(index) || activeIndex.value === index) return
  activeIndex.value = index
}

function selectOption(index: number) {
  const option = props.options[index]
  if (!option || option.disabled || props.disabled) return

  closeMenu()
  if (option.value !== props.modelValue) emit('update:modelValue', option.value)
  emit('change', option.value)
  void nextTick(() => triggerRef.value?.focus())
}

function selectActiveOption() {
  if (activeIndex.value >= 0) selectOption(activeIndex.value)
}

function handleTriggerKeydown(event: KeyboardEvent) {
  if (props.disabled) return

  if (event.key === 'Escape') {
    if (!isOpen.value) return
    event.preventDefault()
    closeMenu(true)
    return
  }

  if (event.key === 'Tab') {
    closeMenu()
    return
  }

  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!isOpen.value) openMenu()
    else moveActive(event.key === 'ArrowDown' ? 1 : -1)
    return
  }

  if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    if (!isOpen.value) openMenu()
    activeIndex.value = event.key === 'Home' ? findFirstEnabled() : findLastEnabled()
    void nextTick(scrollActiveOption)
    return
  }

  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (!isOpen.value) openMenu()
    else selectActiveOption()
  }
}

function handleDocumentPointerDown(event: PointerEvent) {
  const target = event.target
  if (target instanceof Node && rootRef.value?.contains(target)) return
  closeMenu()
}

function handleDocumentScroll(event: Event) {
  const target = event.target
  if (target instanceof Node && rootRef.value?.contains(target)) return
  closeMenu()
}

function handleWindowResize() {
  closeMenu()
}

function setOptionRef(element: HTMLElement | null, index: number) {
  if (element) optionRefs.value[index] = element
}

watch(isOpen, (open) => {
  if (open) {
    addDocumentListeners()
    void nextTick(scrollActiveOption)
  } else {
    removeDocumentListeners()
  }
})

watch(() => props.modelValue, () => {
  if (isOpen.value) syncActiveIndex()
})

watch(() => props.options, () => {
  if (isOpen.value) syncActiveIndex()
}, { deep: true })

onBeforeUnmount(() => {
  removeDocumentListeners()
})
</script>

<template>
  <div
    ref="rootRef"
    v-bind="rootAttrs"
    class="base-select"
    :class="[
      `base-select--${size}`,
      {
        'base-select--block': block,
        'base-select--open': isOpen,
      },
    ]"
  >
    <button
      ref="triggerRef"
      v-bind="triggerAttrs"
      :id="controlId"
      type="button"
      role="combobox"
      class="base-select__trigger"
      :class="{ 'base-select__trigger--placeholder': isPlaceholder }"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-describedby="ariaDescribedby"
      :aria-invalid="ariaInvalid"
      :aria-required="required || undefined"
      aria-haspopup="listbox"
      aria-autocomplete="none"
      :aria-expanded="isOpen"
      :aria-controls="listboxId"
      :aria-activedescendant="activeDescendant"
      @click="toggleMenu"
      @keydown="handleTriggerKeydown"
    >
      <span class="base-select__value">{{ displayLabel }}</span>
      <span class="base-select__arrow" aria-hidden="true"></span>
    </button>

    <input
      v-if="name"
      class="base-select__hidden-input"
      type="hidden"
      :name="name"
      :value="modelValue"
      :disabled="disabled"
    />

    <Transition name="base-select-menu">
      <div
        v-if="isOpen"
        ref="menuRef"
        :id="listboxId"
        class="base-select__menu"
        role="listbox"
        :aria-label="ariaLabel"
        @pointerdown.stop
      >
        <div
          v-for="(option, index) in options"
          :key="option.value"
          :ref="(element) => setOptionRef(element as HTMLElement | null, index)"
          class="base-select__option"
          :class="{
            'base-select__option--active': activeIndex === index,
            'base-select__option--selected': modelValue === option.value,
            'base-select__option--disabled': option.disabled,
          }"
          role="option"
          :id="`${listboxId}-option-${index}`"
          :aria-selected="modelValue === option.value"
          :aria-disabled="option.disabled || undefined"
          @pointermove="setActiveIndex(index)"
          @click.stop="selectOption(index)"
        >
          <span class="base-select__option-label">{{ option.label }}</span>
          <span class="base-select__option-check" aria-hidden="true">
            {{ modelValue === option.value ? '✓' : '' }}
          </span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.base-select {
  position: relative;
  z-index: 1;
  display: inline-flex;
  min-width: 0;
  color: var(--color-text);
  font-family: inherit;
}

.base-select--block {
  display: flex;
  width: 100%;
}

.base-select--open {
  z-index: 40;
}

.base-select__trigger {
  box-sizing: border-box;
  display: flex;
  width: 100%;
  min-width: 0;
  height: 36px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  appearance: none;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
  padding: 0 14px 0 12px;
  font: inherit;
  font-size: 13px;
  line-height: 1.2;
  text-align: left;
  outline: none;
  transition: border-color 0.2s, background-color 0.2s, box-shadow 0.2s;
}

.base-select--sm .base-select__trigger {
  height: 32px;
  gap: 10px;
  padding-right: 11px;
  padding-left: 10px;
  font-size: 12px;
}

.base-select__trigger:hover:not(:disabled) {
  border-color: var(--color-text-tertiary);
  background: var(--color-hover);
}

.base-select__trigger:focus-visible {
  border-color: var(--color-primary);
  outline: 2px solid color-mix(in srgb, var(--color-primary) 24%, transparent);
  outline-offset: 1px;
  box-shadow: 0 0 0 1px var(--color-primary);
}

.base-select__trigger[aria-invalid='true'] {
  border-color: var(--color-error);
}

.base-select__trigger[aria-invalid='true']:focus-visible {
  outline-color: color-mix(in srgb, var(--color-error) 22%, transparent);
  box-shadow: 0 0 0 1px var(--color-error);
}

.base-select__trigger:disabled {
  cursor: not-allowed;
  opacity: 0.6;
  background: var(--color-hover);
}

.base-select__value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.base-select__trigger--placeholder .base-select__value {
  color: var(--color-text-secondary);
}

.base-select__arrow {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  margin-top: -4px;
  border-right: 1.5px solid var(--color-text-secondary);
  border-bottom: 1.5px solid var(--color-text-secondary);
  pointer-events: none;
  transform: rotate(45deg);
  transition: border-color 0.2s, opacity 0.2s, transform 0.2s;
}

.base-select--sm .base-select__arrow {
  width: 6px;
  height: 6px;
}

.base-select--open .base-select__arrow {
  margin-top: 4px;
  transform: rotate(225deg);
}

.base-select__trigger:focus-visible .base-select__arrow,
.base-select--open .base-select__arrow {
  border-color: var(--color-primary);
}

.base-select__trigger[aria-invalid='true'] .base-select__arrow {
  border-color: var(--color-error);
}

.base-select__trigger:disabled .base-select__arrow {
  opacity: 0.6;
}

.base-select__hidden-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}

.base-select__menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 1000;
  display: flex;
  width: max-content;
  min-width: 100%;
  max-width: min(320px, calc(100vw - 16px));
  max-height: 240px;
  flex-direction: column;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  padding: 4px;
  box-shadow: 0 8px 24px rgba(45, 45, 45, 0.14);
}

.base-select--block .base-select__menu {
  width: 100%;
}

.base-select__option {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-radius: 6px;
  color: var(--color-text);
  cursor: pointer;
  padding: 7px 9px;
  font-size: 13px;
  line-height: 1.35;
  white-space: nowrap;
  transition: background-color 0.15s, color 0.15s;
}

.base-select--sm .base-select__option {
  min-height: 30px;
  padding: 6px 8px;
  font-size: 12px;
}

.base-select__option--active {
  background: var(--color-hover);
}

.base-select__option--selected {
  background: var(--color-primary-light);
  color: var(--color-primary-dark);
  font-weight: 500;
}

.base-select__option--selected.base-select__option--active {
  background: var(--color-primary-light);
}

.base-select__option--disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.base-select__option-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.base-select__option-check {
  width: 14px;
  flex: 0 0 14px;
  color: var(--color-primary-dark);
  text-align: center;
}

.base-select-menu-enter-active,
.base-select-menu-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}

.base-select-menu-enter-from,
.base-select-menu-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (prefers-reduced-motion: reduce) {
  .base-select__trigger,
  .base-select__arrow,
  .base-select__option,
  .base-select-menu-enter-active,
  .base-select-menu-leave-active {
    transition: none;
  }
}
</style>
