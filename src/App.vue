<script setup lang="ts">
import { App as CapacitorApp } from '@capacitor/app'
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'

type TimeMode = 'countdown' | 'clock'
type ClockDay = '今日' | '明日'
type DialogName = 'crop' | 'settings'

interface CropConfig {
  name: string
  baseMinutes: number
  waterMaxMinutes: number
}

interface CalculationInput {
  now: Date
  crop: CropConfig
}

interface CalculationResult {
  matureLeft: number
  waterLeftInput: number
  elapsedSinceLastWater: number
  currentWaterReduce: number
  matureAfterWater: number
  fastestLeft: number
  fastestEta: Date
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
const result = ref<string>('请输入数据后点击“计算”按钮计算；\n\n或者在最后一个输入框按回车计算；\n\n计算结果将会显示在这里。')
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

function calculate(): void {
  try {
    clearError()
    const crop = currentCrop.value
    const now = new Date()
    const calculationInput: CalculationInput = { now, crop }
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
    const fastestEta = new Date(now.getTime() + Math.ceil(fastestLeft * 60) * 1000)
    const calculationResult: CalculationResult = { matureLeft, waterLeftInput, elapsedSinceLastWater, currentWaterReduce, matureAfterWater, fastestLeft, fastestEta }
    void calculationInput
    void calculationResult

    result.value = `当前按【${crop.name}】计算（成熟时间输入：${TIME_MODE_LABELS[timeMode.value]}）\n\n距上次浇水：${formatMinutes(elapsedSinceLastWater)}\n本次可减少：${formatMinutes(currentWaterReduce)}\n浇水后剩余：${formatMinutes(matureAfterWater)}\n\n理论最快还需：${formatMinutes(fastestLeft)}\n预计最快成熟时间：\n${formatDateTime(fastestEta)}`
  } catch (exception: unknown) {
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
  result.value = '请输入数据后点击计算。\n\n也可以在最后一个输入框按回车计算。'
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
  lastFocusedElement.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
  activeDialog.value = dialogName
}

function closeDialog(): void {
  const focusTarget = lastFocusedElement.value
  activeDialog.value = null
  nextTick(() => {
    if (focusTarget?.isConnected) focusTarget.focus()
  })
}

function handleDialogKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.preventDefault()
  closeDialog()
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

function shouldAutoAdvance(value: string, maxValue: number): boolean {
  return autoAdvanceEnabled.value && value !== '' && (value.length >= String(maxValue).length || Number(value) * 10 > maxValue)
}

function advanceIfInputIsComplete(input: HTMLInputElement, maxValue: number, nextRef: MaybeInputRef): void {
  const nextInput = resolveInputElement(nextRef)
  if (!nextInput || !shouldAutoAdvance(input.value.trim(), maxValue)) return
  scheduleFocusInput(nextInput)
}

function sanitizeNumber(event: NumericInputEvent, maxValue: number, nextRef: MaybeInputRef = null, autoCalculateOnTwoDigitMinute = false): void {
  if (!isHtmlInputElement(event.target)) return
  const cleaned = event.target.value.replace(/\D/g, '')
  const normalized = cleaned === '' ? '' : String(Math.min(Number(cleaned), maxValue))
  setInputModel(event.target, normalized)
  event.target.value = normalized

  if (autoCalculateOnTwoDigitMinute) {
    maybeAutoCalculateFromWaterMinute(normalized)
    return
  }
  advanceIfInputIsComplete(event.target, maxValue, nextRef)
}

function maybeAutoCalculateFromWaterMinute(value: string): void {
  if (!autoAdvanceEnabled.value) return
  if (!/^\d{2}$/.test(value) || Number(value) > 59) return
  if (value === lastAutoCalculatedWaterMinute.value) return
  lastAutoCalculatedWaterMinute.value = value
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

            <div v-if="needsManualDay" class="day-switch" role="group" aria-label="成熟日期">
              <button type="button" :class="{ active: clockDay === CLOCK_DAY_TODAY }" @click="setClockDay(CLOCK_DAY_TODAY)">今日</button>
              <button type="button" :class="{ active: clockDay === CLOCK_DAY_TOMORROW }" @click="setClockDay(CLOCK_DAY_TOMORROW)">明日</button>
            </div>
            <span v-else-if="isClockMode" class="auto-day">{{ clockAutoDay }}</span>
          </div>

          <div class="time-line">
            <span class="row-label">{{ isClockMode ? '成熟时间' : '成熟剩余' }}</span>
            <div class="time-inputs">
              <input ref="matureHourInput" v-model="matureHour" class="time-input" inputmode="numeric" autocomplete="off" aria-label="成熟时间小时" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event, matureMinuteInput)" @input="sanitizeNumber($event, matureHourMax, matureMinuteInput)" />
              <span class="unit-label">{{ isClockMode ? '点' : '小时' }}</span>
              <input ref="matureMinuteInput" v-model="matureMinute" class="time-input minute" inputmode="numeric" autocomplete="off" aria-label="成熟时间分钟" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event, waterHourInput)" @input="sanitizeNumber($event, 59, waterHourInput)" />
              <span class="unit-label suffix-label">{{ isClockMode ? '分' : '分钟' }}</span>
            </div>
          </div>

          <div class="time-line">
            <span class="row-label">水分剩余</span>
            <div class="time-inputs">
              <input ref="waterHourInput" v-model="waterHour" class="time-input" inputmode="numeric" autocomplete="off" aria-label="水分剩余小时" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event, waterMinuteInput)" @input="sanitizeNumber($event, waterHourMax, waterMinuteInput)" />
              <span class="unit-label">小时</span>
              <input ref="waterMinuteInput" v-model="waterMinute" class="time-input minute" inputmode="numeric" autocomplete="off" aria-label="水分剩余分钟" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="handleInputEnter($event)" @input="sanitizeNumber($event, 59, null, true)" />
              <span class="unit-label suffix-label">分钟</span>
            </div>
          </div>

          <p class="reference">{{ referenceText }}</p>
        </form>

        <section class="result-card" aria-label="计算结果">
          <div class="result-heading">
            <span>结果</span>
            <span v-if="error" class="error-inline">{{ error }}</span>
          </div>
          <pre>{{ error || result }}</pre>
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
        <section class="dialog-card crop-dialog" role="dialog" aria-modal="true" aria-labelledby="crop-dialog-title" tabindex="-1">
          <div class="dialog-head">
            <h2 id="crop-dialog-title">选择作物</h2>
            <button class="close-button" type="button" aria-label="关闭作物选择" @click="closeDialog">×</button>
          </div>
          <div class="crop-options">
            <button v-for="crop in crops" :key="crop.name" type="button" :class="{ active: crop.name === cropName }" @click="setCrop(crop)">{{ crop.name }}</button>
          </div>
        </section>
      </div>

      <div v-if="activeDialog === 'settings'" class="dialog-backdrop" role="presentation" @click.self="closeDialog" @keydown="handleDialogKeydown">
        <section class="dialog-card settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-dialog-title" tabindex="-1">
          <div class="dialog-head">
            <h2 id="settings-dialog-title">设置</h2>
            <button class="close-button" type="button" aria-label="关闭设置" @click="closeDialog">×</button>
          </div>
          <label class="switch-row">
            <span>输入完整后自动跳到下一项</span>
            <input v-model="autoAdvanceEnabled" class="sr-only" type="checkbox" />
            <span class="switch-control" :class="{ active: autoAdvanceEnabled }" aria-hidden="true"></span>
          </label>
        </section>
      </div>
    </teleport>
  </div>
</template>
