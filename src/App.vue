<script setup lang="ts">
import { App as CapacitorApp } from '@capacitor/app'
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'

type TimeMode = 'countdown' | 'clock'
type ClockDay = '今日' | '明日'
type DialogName = 'crop' | 'settings' | 'autoAdvanceHelp'

interface CropConfig {
  name: string
  baseMinutes: number
  waterMaxMinutes: number
}

interface CalculationResult {
  cropName: string
  timeModeLabel: string
  matureLeft: number
  waterLeftInput: number
  elapsedSinceLastWater: number
  currentWaterReduce: number
  matureAfterWater: number
  fastestLeft: number
  savedMinutes: number
  fastestEta: Date
}

interface AutoAdvanceDecision {
  shouldAdvance: boolean
  resolvedDay?: ClockDay
}

type InputRef = Ref<HTMLInputElement | null>
type MaybeInputRef = InputRef | HTMLInputElement | null
type NumericInputEvent = Event
type NumericKeyboardEvent = KeyboardEvent

const TIME_MODE_COUNTDOWN: TimeMode = 'countdown'
const TIME_MODE_CLOCK: TimeMode = 'clock'
const TIME_MODE_LABELS: Record<TimeMode, string> = {
  [TIME_MODE_COUNTDOWN]: '倒计时',
  [TIME_MODE_CLOCK]: '具体时间',
}
const CLOCK_DAY_TODAY: ClockDay = '今日'
const CLOCK_DAY_TOMORROW: ClockDay = '明日'
const STORAGE_KEY = 'farm-calculator-time-mode'
const AUTO_ADVANCE_STORAGE_KEY = 'farm-calculator-auto-advance'
const BACKSPACE_CLEAR_PRESS_COUNT = 3
const BACKSPACE_CLEAR_WINDOW_MS = 800

const crops: CropConfig[] = [
  { name: '8小时作物', baseMinutes: 8 * 60, waterMaxMinutes: 2 * 60 + 40 },
  { name: '16小时作物', baseMinutes: 16 * 60, waterMaxMinutes: 5 * 60 + 20 },
  { name: '32小时作物', baseMinutes: 32 * 60, waterMaxMinutes: 10 * 60 + 40 },
]

const cropName = ref<string>('16小时作物')
const timeMode = ref<TimeMode>(TIME_MODE_COUNTDOWN)
const clockDay = ref<ClockDay>(CLOCK_DAY_TODAY)
const matureHour = ref<string>('')
const matureMinute = ref<string>('')
const waterHour = ref<string>('')
const waterMinute = ref<string>('')
const initialResultHint = '请输入数据后点击“计算”按钮计算；\n\n或者在最后一个输入框按回车计算；\n\n计算结果将会显示在这里。'
const resultHint = ref<string>(initialResultHint)
const calculationResult = ref<CalculationResult | null>(null)
const error = ref<string>('')
const backspacePressTimes = ref<number[]>([])
const autoAdvanceEnabled = ref<boolean>(true)
const activeDialog = ref<DialogName | null>(null)
const lastFocusedElement = ref<HTMLElement | null>(null)
const lastAutoCalculatedWaterMinute = ref<string>('')
const matureHourInput = ref<HTMLInputElement | null>(null)
const matureMinuteInput = ref<HTMLInputElement | null>(null)
const waterHourInput = ref<HTMLInputElement | null>(null)
const waterMinuteInput = ref<HTMLInputElement | null>(null)
const cropDialog = ref<HTMLElement | null>(null)
const settingsDialog = ref<HTMLElement | null>(null)
const autoAdvanceHelpDialog = ref<HTMLElement | null>(null)
const autoAdvanceHelpButton = ref<HTMLButtonElement | null>(null)

const currentCrop = computed(() => crops.find((crop) => crop.name === cropName.value) ?? crops[1])
const cropButtonText = computed(() => currentCrop.value.name.replace('作物', ''))
const isClockMode = computed(() => timeMode.value === TIME_MODE_CLOCK)
const needsManualDay = computed(() => isClockMode.value && currentCrop.value.baseMinutes >= 32 * 60)
const clockAutoDay = computed(() => {
  if (!isClockMode.value || needsManualDay.value) return '--'
  const hour = toOptionalInteger(matureHour.value)
  const minute = toOptionalInteger(matureMinute.value)
  if (hour === null || minute === null || hour >= 24 || minute >= 60) return '--'
  const now = new Date()
  const todayTime = new Date(now)
  todayTime.setHours(hour, minute, 0, 0)
  return todayTime > now ? CLOCK_DAY_TODAY : CLOCK_DAY_TOMORROW
})
const referenceText = computed(() => {
  const crop = currentCrop.value
  return `基础成熟 ${formatMinutes(crop.baseMinutes)}；水分最大维持 ${formatMinutes(crop.waterMaxMinutes)}；满额浇水减少 ${formatMinutes(crop.waterMaxMinutes / 4)}；理论最快 ${formatMinutes((crop.baseMinutes - crop.waterMaxMinutes / 4) * 4 / 5)}。`
})
const matureHourMax = computed(() => isClockMode.value ? 23 : currentCrop.value.baseMinutes / 60)
const waterHourMax = computed(() => Math.floor(currentCrop.value.waterMaxMinutes / 60))

let removeBackButtonListener: (() => void) | undefined

onMounted(() => {
  const savedMode = localStorage.getItem(STORAGE_KEY)
  if (savedMode === TIME_MODE_COUNTDOWN || savedMode === TIME_MODE_CLOCK) timeMode.value = savedMode
  const savedAutoAdvance = localStorage.getItem(AUTO_ADVANCE_STORAGE_KEY)
  autoAdvanceEnabled.value = savedAutoAdvance === null ? true : savedAutoAdvance === 'true'
  void CapacitorApp.addListener('backButton', ({ canGoBack }) => {
    if (activeDialog.value) {
      closeDialog()
      return
    }
    if (!canGoBack) return
    window.history.back()
  }).then((handle) => {
    removeBackButtonListener = () => void handle.remove()
  })
  nextTick(() => matureHourInput.value?.focus())
})

onUnmounted(() => {
  removeBackButtonListener?.()
})

watch(timeMode, (mode) => {
  localStorage.setItem(STORAGE_KEY, mode)
  clearError()
  lastAutoCalculatedWaterMinute.value = ''
  nextTick(() => matureHourInput.value?.focus())
})

watch(autoAdvanceEnabled, (enabled) => {
  localStorage.setItem(AUTO_ADVANCE_STORAGE_KEY, String(enabled))
  lastAutoCalculatedWaterMinute.value = ''
})

watch(waterMinute, (value) => {
  if (value !== lastAutoCalculatedWaterMinute.value) lastAutoCalculatedWaterMinute.value = ''
})

function toOptionalInteger(value: string): number | null {
  const text = String(value ?? '').trim()
  if (text === '') return 0
  if (!/^\d+$/.test(text)) return null
  return Number(text)
}

function readNonNegativeInt(value: string, fieldName: string): number {
  const text = String(value ?? '').trim()
  if (text === '') return 0
  if (!/^\d+$/.test(text)) throw new Error(`${fieldName} 只能输入非负整数。`)
  return Number(text)
}

function readMinute(value: string, fieldName: string): number {
  const minute = readNonNegativeInt(value, fieldName)
  if (minute >= 60) throw new Error(`${fieldName} 必须在 0-59 之间。`)
  return minute
}

function ceilPositive(value: number): number {
  if (value <= 0) return 0
  return Math.ceil(value)
}

function formatMinutes(minutes: number): string {
  const totalSeconds = ceilPositive(minutes * 60)
  if (totalSeconds <= 0) return '0分钟'
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60
  return [hours ? `${hours}小时` : '', mins ? `${mins}分钟` : '', secs ? `${secs}秒` : ''].join('')
}

function formatDateTime(date: Date): string {
  const pad = (num: number): string => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function readMatureLeft(now: Date, crop: CropConfig): number {
  if (isClockMode.value) {
    const hour = readNonNegativeInt(matureHour.value, '预计成熟时间小时')
    const minute = readMinute(matureMinute.value, '预计成熟时间分钟')
    if (hour >= 24) throw new Error('预计成熟时间小时必须在 0-23 之间。')
    const todayTime = new Date(now)
    todayTime.setHours(hour, minute, 0, 0)
    const tomorrowTime = new Date(todayTime)
    tomorrowTime.setDate(tomorrowTime.getDate() + 1)
    if (crop.baseMinutes >= 32 * 60) {
      if (clockDay.value === CLOCK_DAY_TODAY) {
        if (todayTime <= now) throw new Error('具体时间输入有误：已选择“今日”，但该时刻已经过去。请改选“明日”或输入晚于当前时间的今日时刻。')
        return clockDeltaMinutes(now, todayTime)
      }
      return clockDeltaMinutes(now, tomorrowTime)
    }
    return clockDeltaMinutes(now, todayTime > now ? todayTime : tomorrowTime)
  }
  return readNonNegativeInt(matureHour.value, '当前成熟剩余小时') * 60 + readMinute(matureMinute.value, '当前成熟剩余分钟')
}

function clockDeltaMinutes(now: Date, target: Date): number {
  return Math.ceil(Math.max(0, target.getTime() - now.getTime()) / 60000)
}

function clockMatureLeftForCandidate(now: Date, crop: CropConfig, hour: number, minute: number, day: ClockDay): number {
  const todayTime = new Date(now)
  todayTime.setHours(hour, minute, 0, 0)
  if (crop.baseMinutes >= 32 * 60) {
    if (day === CLOCK_DAY_TODAY) return todayTime > now ? clockDeltaMinutes(now, todayTime) : -1
    const tomorrowTime = new Date(todayTime)
    tomorrowTime.setDate(tomorrowTime.getDate() + 1)
    return clockDeltaMinutes(now, tomorrowTime)
  }
  const tomorrowTime = new Date(todayTime)
  tomorrowTime.setDate(tomorrowTime.getDate() + 1)
  return clockDeltaMinutes(now, todayTime > now ? todayTime : tomorrowTime)
}

function minuteDecisionValue(): number | null | undefined {
  const text = matureMinute.value.trim()
  if (text === '') return undefined
  if (!/^\d+$/.test(text)) return null
  const minute = Number(text)
  return minute >= 0 && minute <= 59 ? minute : null
}

function clockHourHasValidMinute(now: Date, crop: CropConfig, hour: number, day: ClockDay, minute: number | null | undefined): boolean {
  if (hour < 0 || hour > 23 || !Number.isInteger(hour)) return false
  if (minute === null) return false
  if (minute !== undefined) {
    const matureLeft = clockMatureLeftForCandidate(now, crop, hour, minute, day)
    return matureLeft > 0 && matureLeft <= crop.baseMinutes
  }

  for (let candidateMinute = 0; candidateMinute <= 59; candidateMinute += 1) {
    const matureLeft = clockMatureLeftForCandidate(now, crop, hour, candidateMinute, day)
    if (matureLeft > 0 && matureLeft <= crop.baseMinutes) return true
  }
  return false
}

function validClockHourValues(now: Date, crop: CropConfig, day: ClockDay, minute: number | null | undefined = undefined): number[] {
  const values = new Set<number>()
  for (let hour = 0; hour <= 23; hour += 1) {
    if (clockHourHasValidMinute(now, crop, hour, day, minute)) values.add(hour)
  }
  return [...values].sort((left, right) => left - right)
}

function mergeUniqueHours(...hourLists: number[][]): number[] {
  return [...new Set(hourLists.flat())].sort((left, right) => left - right)
}

function hasLongerHourWithPrefix(prefix: string, allowedHours: number[]): boolean {
  return allowedHours.some((hour) => {
    const text = String(hour)
    return text.length > prefix.length && text.startsWith(prefix)
  })
}

function decideManualDayClockHourAutoAdvance(value: string, now: Date): AutoAdvanceDecision {
  const numericValue = Number(value)
  const crop = currentCrop.value
  const minute = minuteDecisionValue()
  const todayHours = validClockHourValues(now, crop, CLOCK_DAY_TODAY, minute)
  const tomorrowHours = validClockHourValues(now, crop, CLOCK_DAY_TOMORROW, minute)
  const allHours = mergeUniqueHours(todayHours, tomorrowHours)
  const todayValid = todayHours.includes(numericValue)
  const tomorrowValid = tomorrowHours.includes(numericValue)

  if (!todayValid && !tomorrowValid) return { shouldAdvance: false }
  if (hasLongerHourWithPrefix(value, allHours)) return { shouldAdvance: false }
  if (todayValid && !tomorrowValid) return { shouldAdvance: true, resolvedDay: CLOCK_DAY_TODAY }
  if (!todayValid && tomorrowValid) return { shouldAdvance: true, resolvedDay: CLOCK_DAY_TOMORROW }
  return { shouldAdvance: true }
}

function decideMatureHourAutoAdvance(value: string, now = new Date()): AutoAdvanceDecision {
  if (!autoAdvanceEnabled.value || value === '' || !/^\d+$/.test(value)) return { shouldAdvance: false }
  const numericValue = Number(value)
  if (!Number.isInteger(numericValue)) return { shouldAdvance: false }
  if (!isClockMode.value) {
    if (numericValue < 0 || numericValue > matureHourMax.value) return { shouldAdvance: false }
    return { shouldAdvance: !hasLongerHourWithPrefix(value, Array.from({ length: Math.floor(matureHourMax.value) + 1 }, (_, index) => index)) }
  }

  if (needsManualDay.value) return decideManualDayClockHourAutoAdvance(value, now)

  const minute = minuteDecisionValue()
  const allowedHours = validClockHourValues(now, currentCrop.value, clockAutoDay.value as ClockDay, minute)
  if (!allowedHours.includes(numericValue)) return { shouldAdvance: false }
  return { shouldAdvance: !hasLongerHourWithPrefix(value, allowedHours) }
}

function decideAutoAdvance(value: string, maxValue: number, input: HTMLInputElement, now = new Date()): AutoAdvanceDecision {
  if (!autoAdvanceEnabled.value || value === '') return { shouldAdvance: false }
  if (input === matureHourInput.value) return decideMatureHourAutoAdvance(value, now)
  return { shouldAdvance: Number(value) <= maxValue && (value.length >= String(maxValue).length || Number(value) * 10 > maxValue) }
}

function calculate(): void {
  try {
    clearError()
    const crop = currentCrop.value
    const now = new Date()
    const matureLeft = readMatureLeft(now, crop)
    const waterLeftInput = readNonNegativeInt(waterHour.value, '当前水分剩余小时') * 60 + readMinute(waterMinute.value, '当前水分剩余分钟')
    if (matureLeft <= 0) throw new Error('当前成熟剩余时间必须大于 0。')
    if (matureLeft > crop.baseMinutes) {
      if (isClockMode.value) throw new Error(`具体时间输入有误：该时刻换算后还需 ${formatMinutes(matureLeft)}，已超过【${crop.name}】的基础成熟时间 ${formatMinutes(crop.baseMinutes)}。请检查作物类型、成熟日期或输入的时分。`)
      throw new Error(`当前成熟剩余时间不能超过【${crop.name}】的基础成熟时间：${formatMinutes(crop.baseMinutes)}。`)
    }
    if (waterLeftInput > crop.waterMaxMinutes) throw new Error(`当前水分还能维持时间不能超过【${crop.name}】的最大水分维持时间：${formatMinutes(crop.waterMaxMinutes)}。`)

    const elapsedSinceLastWater = Math.max(0, Math.min(crop.waterMaxMinutes, crop.waterMaxMinutes - waterLeftInput))
    const currentWaterReduce = Math.min(matureLeft, elapsedSinceLastWater / 4)
    const matureAfterWater = Math.max(0, matureLeft - currentWaterReduce)
    const fastestLeft = matureAfterWater * 4 / 5
    const savedMinutes = Math.max(0, Math.min(matureLeft, matureLeft - fastestLeft))
    const fastestEta = new Date(now.getTime() + Math.ceil(fastestLeft * 60) * 1000)

    calculationResult.value = {
      cropName: crop.name,
      timeModeLabel: TIME_MODE_LABELS[timeMode.value],
      matureLeft,
      waterLeftInput,
      elapsedSinceLastWater,
      currentWaterReduce,
      matureAfterWater,
      fastestLeft,
      savedMinutes,
      fastestEta,
    }
  } catch (exception: unknown) {
    calculationResult.value = null
    error.value = exception instanceof Error ? exception.message : '计算失败，请检查输入。'
  }
}

function clearInputs(): void {
  matureHour.value = ''
  matureMinute.value = ''
  waterHour.value = ''
  waterMinute.value = ''
  backspacePressTimes.value = []
  lastAutoCalculatedWaterMinute.value = ''
  error.value = ''
  calculationResult.value = null
  resultHint.value = initialResultHint
  nextTick(() => matureHourInput.value?.focus())
}

function clearError(): void {
  error.value = ''
}

function cycleTimeMode(): void {
  timeMode.value = isClockMode.value ? TIME_MODE_COUNTDOWN : TIME_MODE_CLOCK
}

function setTimeMode(mode: TimeMode): void {
  timeMode.value = mode
}

function setClockDay(day: ClockDay): void {
  clockDay.value = day
  clearError()
}

function setCrop(crop: CropConfig): void {
  cropName.value = crop.name
  clearError()
  closeDialog()
}

function openDialog(dialogName: DialogName): void {
  if (dialogName === 'autoAdvanceHelp' && activeDialog.value === 'settings') {
    activeDialog.value = dialogName
    focusActiveDialog()
    return
  }
  lastFocusedElement.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
  activeDialog.value = dialogName
  focusActiveDialog()
}

function isDialogOpen(dialogName: DialogName): boolean {
  return activeDialog.value === dialogName
}

function currentDialogElement(): HTMLElement | null {
  if (activeDialog.value === 'crop') return cropDialog.value
  if (activeDialog.value === 'settings') return settingsDialog.value
  if (activeDialog.value === 'autoAdvanceHelp') return autoAdvanceHelpDialog.value
  return null
}

function focusableDialogElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>('button, input, [href], [tabindex]:not([tabindex="-1"])'))
    .filter((element) => !element.hasAttribute('disabled') && element.tabIndex !== -1)
}

function focusActiveDialog(): void {
  nextTick(() => {
    const dialog = currentDialogElement()
    if (!dialog) return
    const firstFocusable = focusableDialogElements(dialog)[0]
    ;(firstFocusable ?? dialog).focus()
  })
}

function closeDialog(): void {
  if (activeDialog.value === 'autoAdvanceHelp') {
    activeDialog.value = 'settings'
    nextTick(() => autoAdvanceHelpButton.value?.focus())
    return
  }

  const focusTarget = lastFocusedElement.value
  activeDialog.value = null
  nextTick(() => {
    if (focusTarget?.isConnected) focusTarget.focus()
  })
}

function trapDialogFocus(event: KeyboardEvent): void {
  const dialog = currentDialogElement()
  if (!dialog) return
  const focusableElements = focusableDialogElements(dialog)
  if (focusableElements.length === 0) {
    event.preventDefault()
    dialog.focus()
    return
  }

  const firstElement = focusableElements[0]
  const lastElement = focusableElements[focusableElements.length - 1]
  if (event.shiftKey && document.activeElement === firstElement) {
    event.preventDefault()
    lastElement.focus()
  } else if (!event.shiftKey && document.activeElement === lastElement) {
    event.preventDefault()
    firstElement.focus()
  }
}

function handleDialogKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeDialog()
    return
  }
  if (event.key === 'Tab') trapDialogFocus(event)
}

function isHtmlInputElement(value: EventTarget | HTMLInputElement | null): value is HTMLInputElement {
  return typeof HTMLInputElement !== 'undefined' && value instanceof HTMLInputElement
}

function orderedInputElements(): HTMLInputElement[] {
  return [matureHourInput.value, matureMinuteInput.value, waterHourInput.value, waterMinuteInput.value].filter(isHtmlInputElement)
}

function focusAdjacentInput(event: NumericKeyboardEvent, step: number): void {
  if (!isHtmlInputElement(event.target)) return
  const inputs = orderedInputElements()
  const currentIndex = inputs.indexOf(event.target)
  if (currentIndex === -1) return
  const nextIndex = Math.min(inputs.length - 1, Math.max(0, currentIndex + step))
  const target = inputs[nextIndex]
  if (!target || target === event.target) return
  focusAndSelectInput(target)
}

function resolveInputElement(inputRef: MaybeInputRef): HTMLInputElement | null {
  if (!inputRef) return null
  if (typeof HTMLInputElement !== 'undefined' && inputRef instanceof HTMLInputElement) return inputRef
  const candidate: unknown = inputRef.value
  if (isHtmlInputElement(candidate as EventTarget | HTMLInputElement | null)) return candidate as HTMLInputElement
  return null
}

function focusAndSelectInput(input: HTMLInputElement): void {
  input.focus()
  input.select()
}

function scheduleFocusInput(input: HTMLInputElement): void {
  if (!autoAdvanceEnabled.value) return
  nextTick(() => {
    setTimeout(() => focusAndSelectInput(input), 0)
  })
}

function setInputModel(input: HTMLInputElement, value: string): void {
  if (input === matureHourInput.value) matureHour.value = value
  if (input === matureMinuteInput.value) matureMinute.value = value
  if (input === waterHourInput.value) waterHour.value = value
  if (input === waterMinuteInput.value) waterMinute.value = value
}

function advanceIfInputIsComplete(input: HTMLInputElement, maxValue: number, nextRef: MaybeInputRef): void {
  const nextInput = resolveInputElement(nextRef)
  if (!nextInput) return
  const decision = decideAutoAdvance(input.value.trim(), maxValue, input)
  if (!decision.shouldAdvance) return
  if (input === matureHourInput.value && decision.resolvedDay && decision.resolvedDay !== clockDay.value) {
    clockDay.value = decision.resolvedDay
    clearError()
  }
  scheduleFocusInput(nextInput)
}

function sanitizeNumber(event: NumericInputEvent, maxValue: number, nextRef: MaybeInputRef = null, autoCalculateOnTwoDigitMinute = false): void {
  if (!isHtmlInputElement(event.target)) return
  const cleaned = event.target.value.replace(/\D/g, '')
  const isOverMax = cleaned !== '' && Number(cleaned) > maxValue
  const normalized = cleaned === '' ? '' : String(Math.min(Number(cleaned), maxValue))
  setInputModel(event.target, normalized)
  event.target.value = normalized

  if (autoCalculateOnTwoDigitMinute) {
    maybeAutoCalculateFromWaterMinute(cleaned, isOverMax)
    return
  }
  advanceIfInputIsComplete(event.target, maxValue, nextRef)
}

function maybeAutoCalculateFromWaterMinute(rawValue: string, isOverMax: boolean): void {
  if (!autoAdvanceEnabled.value || isOverMax) return
  if (!/^\d{2}$/.test(rawValue) || Number(rawValue) > 59) return
  if (rawValue === lastAutoCalculatedWaterMinute.value) return
  lastAutoCalculatedWaterMinute.value = rawValue
  calculate()
}

function handleInputEnter(event: NumericKeyboardEvent, nextRef: MaybeInputRef = null): void {
  event.preventDefault()
  const nextInput = resolveInputElement(nextRef)
  if (nextInput) focusAndSelectInput(nextInput)
  else calculate()
}

function handleGlobalKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && activeDialog.value) {
    event.preventDefault()
    closeDialog()
    return
  }
  if (activeDialog.value) return
  if (event.altKey && event.key.toLowerCase() === 'x') {
    event.preventDefault()
    cycleTimeMode()
    return
  }
  if (event.key === 'Backspace') {
    const now = Date.now()
    backspacePressTimes.value = backspacePressTimes.value.filter((timestamp) => timestamp >= now - BACKSPACE_CLEAR_WINDOW_MS)
    backspacePressTimes.value.push(now)
    if (backspacePressTimes.value.length >= BACKSPACE_CLEAR_PRESS_COUNT) {
      event.preventDefault()
      clearInputs()
    }
  }
}
</script>

<template>
  <div class="app-shell" @keydown="handleGlobalKeydown">
    <header class="app-header">
      <h1>成熟计算器</h1>
      <button class="icon-button" type="button" aria-label="打开设置" @click="openDialog('settings')">⚙️</button>
    </header>

    <main class="app-main">
      <div class="page-shell">
        <p class="notice-card">作物类型是 8/16/32 小时作物，不是当前剩余成熟时间。</p>

        <form id="calculator-form" class="calculator-card" @submit.prevent="calculate">
          <div class="mode-line">
            <div class="mode-switch" role="group" aria-label="成熟时间输入模式">
              <button class="mode-option" type="button" :class="{ active: !isClockMode }" :aria-pressed="!isClockMode" @click="setTimeMode(TIME_MODE_COUNTDOWN)">倒计时</button>
              <button class="mode-option" type="button" :class="{ active: isClockMode }" :aria-pressed="isClockMode" @click="setTimeMode(TIME_MODE_CLOCK)">具体时间</button>
              <span class="mode-thumb" :class="{ right: isClockMode }" aria-hidden="true"></span>
            </div>

            <div class="mode-extra">
              <div v-if="needsManualDay" class="day-switch" role="group" aria-label="成熟日期">
                <button type="button" :class="{ active: clockDay === CLOCK_DAY_TODAY }" @click="setClockDay(CLOCK_DAY_TODAY)">今日</button>
                <button type="button" :class="{ active: clockDay === CLOCK_DAY_TOMORROW }" @click="setClockDay(CLOCK_DAY_TOMORROW)">明日</button>
              </div>
              <span v-else-if="isClockMode" class="auto-day">{{ clockAutoDay }}</span>
            </div>
          </div>

          <div class="time-line">
            <span class="row-label">{{ isClockMode ? '预计成熟时间' : '成熟剩余' }}</span>
            <div class="time-inputs">
              <input ref="matureHourInput" v-model="matureHour" class="time-input" inputmode="numeric" autocomplete="off" aria-label="成熟时间小时" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event, matureMinuteInput)" @input="sanitizeNumber($event, matureHourMax, matureMinuteInput)" />
              <span class="unit-label">{{ isClockMode ? '点' : '小时' }}</span>
              <input ref="matureMinuteInput" v-model="matureMinute" class="time-input minute" inputmode="numeric" autocomplete="off" aria-label="成熟时间分钟" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event, waterHourInput)" @input="sanitizeNumber($event, 59, waterHourInput)" />
              <span class="unit-label suffix-label">{{ isClockMode ? '分' : '分钟' }}</span>
            </div>
          </div>

          <div class="time-line">
            <span class="row-label">当前水分还能维持</span>
            <div class="time-inputs">
              <input ref="waterHourInput" v-model="waterHour" class="time-input" inputmode="numeric" autocomplete="off" aria-label="水分剩余小时" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event, waterMinuteInput)" @input="sanitizeNumber($event, waterHourMax, waterMinuteInput)" />
              <span class="unit-label">小时</span>
              <input ref="waterMinuteInput" v-model="waterMinute" class="time-input minute" inputmode="numeric" autocomplete="off" aria-label="水分剩余分钟" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event)" @input="sanitizeNumber($event, 59, null, true)" />
              <span class="unit-label suffix-label">分钟</span>
            </div>
          </div>

          <p class="reference">{{ referenceText }}</p>
        </form>

        <section class="result-card" aria-label="计算结果" aria-live="polite">
          <div class="result-heading">
            <span>结果</span>
            <span v-if="error" class="error-inline">计算失败</span>
          </div>

          <div v-if="error" class="result-scroll result-message error-message">{{ error }}</div>

          <div v-else-if="calculationResult" class="result-scroll result-content">
            <p class="result-snapshot">{{ calculationResult.cropName }} · {{ calculationResult.timeModeLabel }}</p>

            <dl class="result-details">
              <div>
                <dt>距上次浇水</dt>
                <dd>{{ formatMinutes(calculationResult.elapsedSinceLastWater) }}</dd>
              </div>
              <div>
                <dt>本次可减少</dt>
                <dd>{{ formatMinutes(calculationResult.currentWaterReduce) }}</dd>
              </div>
              <div>
                <dt>浇水后剩余</dt>
                <dd>{{ formatMinutes(calculationResult.matureAfterWater) }}</dd>
              </div>
              <div>
                <dt>理论最快还需</dt>
                <dd>{{ formatMinutes(calculationResult.fastestLeft) }}</dd>
              </div>
            </dl>

            <section class="saved-card" aria-label="理论总计可节省">
              <span>理论总计可节省</span>
              <strong>{{ formatMinutes(calculationResult.savedMinutes) }}</strong>
              <small>相较于当前原始成熟剩余时间，已包含本次浇水减少与后续理论加速收益。</small>
            </section>

            <section class="eta-card" aria-label="预计最快成熟时间">
              <span>预计最快成熟时间</span>
              <time :datetime="calculationResult.fastestEta.toISOString()">{{ formatDateTime(calculationResult.fastestEta) }}</time>
            </section>
          </div>

          <pre v-else class="result-scroll result-placeholder">{{ resultHint }}</pre>
        </section>
      </div>
    </main>

    <footer class="app-footer">
      <button class="footer-button secondary" type="button" @click="clearInputs">清空</button>
      <button class="footer-button crop-button" type="button" aria-haspopup="dialog" :aria-expanded="activeDialog === 'crop'" @click="openDialog('crop')">{{ cropButtonText }}</button>
      <button class="footer-button primary" type="submit" form="calculator-form">计算</button>
    </footer>

    <teleport to="body">
      <div v-if="activeDialog === 'crop'" class="dialog-backdrop" role="presentation" @click.self="closeDialog" @keydown="handleDialogKeydown">
        <section ref="cropDialog" class="dialog-card crop-dialog" role="dialog" aria-modal="true" aria-labelledby="crop-dialog-title" tabindex="-1">
          <div class="dialog-head">
            <h2 id="crop-dialog-title">选择作物</h2>
            <button class="close-button" type="button" aria-label="关闭作物选择" @click="closeDialog">×</button>
          </div>
          <div class="crop-options">
            <button v-for="crop in crops" :key="crop.name" type="button" :class="{ active: crop.name === cropName }" @click="setCrop(crop)">{{ crop.name }}</button>
          </div>
        </section>
      </div>



      <div v-if="activeDialog === 'autoAdvanceHelp'" class="dialog-backdrop" role="presentation" @click.self="closeDialog" @keydown="handleDialogKeydown">
        <section ref="autoAdvanceHelpDialog" class="dialog-card help-dialog" role="dialog" aria-modal="true" aria-labelledby="auto-advance-help-title" tabindex="-1">
          <div class="dialog-head">
            <h2 id="auto-advance-help-title">自动跳转说明</h2>
            <button class="close-button" type="button" aria-label="关闭自动跳转说明" @click="closeDialog">×</button>
          </div>

          <div class="help-body">
            <p>开启时，输入被判定为完整且无需继续等待下一位后，会自动聚焦并全选下一输入框。</p>
            <p>具体时间模式会结合当前时间、作物最大成熟时长及今日/明日的有效范围判断，不只是按固定两位数跳转。</p>
            <p>最后一个“水分分钟”输入两位合法数字 <code>00–59</code> 后，只自动计算一次。</p>
            <p>关闭时，数字输入不自动换焦点、不自动切换日期、不自动计算；按 Enter 前往下一项，最后一项 Enter 计算。</p>

            <section class="help-example" aria-labelledby="countdown-help-title">
              <h3 id="countdown-help-title">倒计时示例</h3>
              <p>选择16小时作物，成熟剩余小时输入 <code>7</code>。因为不存在 <code>70–79</code> 这类有效小时，程序会把 <code>7</code> 视为完整值并跳到分钟；分钟输入 <code>30</code> 后继续跳到水分小时。</p>
            </section>

            <section class="help-example" aria-labelledby="clock-help-title">
              <h3 id="clock-help-title">具体时间示例</h3>
              <p>例如当前约12:00，选择32小时作物并输入成熟小时 <code>6</code>。今日06:xx已过去，而明日06:xx仍在未来32小时内，程序会自动选择“明日”并跳到分钟；若输入 <code>1</code> 且 <code>10–19</code> 中仍存在有效时间，则等待第二位。</p>
            </section>
          </div>

          <button class="confirm-button" type="button" @click="closeDialog">知道了</button>
        </section>
      </div>

      <div v-if="activeDialog === 'settings'" class="dialog-backdrop" role="presentation" @click.self="closeDialog" @keydown="handleDialogKeydown">
        <section ref="settingsDialog" class="dialog-card settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-dialog-title" tabindex="-1">
          <div class="dialog-head">
            <h2 id="settings-dialog-title">设置</h2>
            <button class="close-button" type="button" aria-label="关闭设置" @click="closeDialog">×</button>
          </div>
          <div class="switch-row">
            <div class="setting-label-group">
              <span id="auto-advance-toggle-label" class="setting-label-text">输入完自动跳转到下一项</span>
              <button ref="autoAdvanceHelpButton" class="help-button" type="button" aria-label="查看自动跳转说明" aria-haspopup="dialog" :aria-expanded="isDialogOpen('autoAdvanceHelp')" @click="openDialog('autoAdvanceHelp')">
                <span class="help-button-glyph" aria-hidden="true">?</span>
              </button>
            </div>
            <label class="switch-toggle">
              <span class="sr-only">输入完自动跳转到下一项</span>
              <input id="auto-advance-toggle" v-model="autoAdvanceEnabled" class="sr-only" type="checkbox" aria-labelledby="auto-advance-toggle-label" />
              <span class="switch-control" :class="{ active: autoAdvanceEnabled }" aria-hidden="true"></span>
            </label>
          </div>
        </section>
      </div>
    </teleport>
  </div>
</template>
