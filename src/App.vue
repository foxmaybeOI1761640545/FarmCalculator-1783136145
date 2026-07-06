<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch, type Ref } from 'vue'

type TimeMode = 'countdown' | 'clock'
type ClockDay = '今日' | '明日'

interface CropConfig {
  name: string
  shortName: string
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
type NumericInputBeforeEvent = InputEvent

const TIME_MODE_COUNTDOWN: TimeMode = 'countdown'
const TIME_MODE_CLOCK: TimeMode = 'clock'
const TIME_MODE_LABELS: Record<TimeMode, string> = {
  [TIME_MODE_COUNTDOWN]: '倒计时',
  [TIME_MODE_CLOCK]: '具体时间',
}
const CLOCK_DAY_TODAY: ClockDay = '今日'
const CLOCK_DAY_TOMORROW: ClockDay = '明日'
const TIME_MODE_STORAGE_KEY = 'farm-calculator-time-mode'
const AUTO_ADVANCE_STORAGE_KEY = 'farm-calculator-auto-advance'
const BACKSPACE_CLEAR_PRESS_COUNT = 3
const BACKSPACE_CLEAR_WINDOW_MS = 800

const crops: CropConfig[] = [
  { name: '8小时作物', shortName: '8小时作物', baseMinutes: 8 * 60, waterMaxMinutes: 2 * 60 + 40 },
  { name: '16小时作物', shortName: '16小时作物', baseMinutes: 16 * 60, waterMaxMinutes: 5 * 60 + 20 },
  { name: '32小时作物', shortName: '32小时作物', baseMinutes: 32 * 60, waterMaxMinutes: 10 * 60 + 40 },
]

const cropName = ref<string>('16小时作物')
const timeMode = ref<TimeMode>(TIME_MODE_COUNTDOWN)
const autoAdvance = ref<boolean>(true)
const clockDay = ref<ClockDay>(CLOCK_DAY_TODAY)
const matureHour = ref<string>('')
const matureMinute = ref<string>('')
const waterHour = ref<string>('')
const waterMinute = ref<string>('')
const result = ref<string>('填写成熟时间和水分时间后点击“计算”。\n\n开启自动跳转时，最后一格输入两位数字会自动计算。')
const error = ref<string>('')
const showCropMenu = ref<boolean>(false)
const showSettings = ref<boolean>(false)
const backspacePressTimes = ref<number[]>([])
const matureHourInput = ref<HTMLInputElement | null>(null)
const matureMinuteInput = ref<HTMLInputElement | null>(null)
const waterHourInput = ref<HTMLInputElement | null>(null)
const waterMinuteInput = ref<HTMLInputElement | null>(null)
const resultPanel = ref<HTMLElement | null>(null)
let autoCalculateQueued = false

const currentCrop = computed(() => crops.find((crop) => crop.name === cropName.value) ?? crops[1])
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
  const fastest = (crop.baseMinutes - crop.waterMaxMinutes / 4) * 4 / 5
  return `基础 ${formatMinutes(crop.baseMinutes)} · 水分上限 ${formatMinutes(crop.waterMaxMinutes)} · 满额浇水后最快 ${formatMinutes(fastest)}`
})
const matureHourMax = computed(() => isClockMode.value ? 23 : currentCrop.value.baseMinutes / 60)
const waterHourMax = computed(() => Math.floor(currentCrop.value.waterMaxMinutes / 60))

onMounted(() => {
  const savedMode = localStorage.getItem(TIME_MODE_STORAGE_KEY)
  if (savedMode === TIME_MODE_COUNTDOWN || savedMode === TIME_MODE_CLOCK) timeMode.value = savedMode
  const savedAutoAdvance = localStorage.getItem(AUTO_ADVANCE_STORAGE_KEY)
  if (savedAutoAdvance === 'true' || savedAutoAdvance === 'false') autoAdvance.value = savedAutoAdvance === 'true'
  nextTick(() => matureHourInput.value?.focus())
})

watch(timeMode, (mode) => {
  localStorage.setItem(TIME_MODE_STORAGE_KEY, mode)
  clearError()
  nextTick(() => matureHourInput.value?.focus())
})

watch(autoAdvance, (enabled) => {
  localStorage.setItem(AUTO_ADVANCE_STORAGE_KEY, String(enabled))
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
        if (todayTime <= now) throw new Error('已选择“今日”，但该时刻已经过去。请改选“明日”或输入更晚的时间。')
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
      if (isClockMode.value) throw new Error(`该时刻换算后还需 ${formatMinutes(matureLeft)}，已超过【${crop.name}】的基础成熟时间。`)
      throw new Error(`当前成熟剩余时间不能超过【${crop.name}】的基础成熟时间：${formatMinutes(crop.baseMinutes)}。`)
    }
    if (waterLeftInput > crop.waterMaxMinutes) throw new Error(`当前水分还能维持时间不能超过【${crop.name}】的最大值：${formatMinutes(crop.waterMaxMinutes)}。`)

    const elapsedSinceLastWater = Math.max(0, Math.min(crop.waterMaxMinutes, crop.waterMaxMinutes - waterLeftInput))
    const currentWaterReduce = Math.min(matureLeft, elapsedSinceLastWater / 4)
    const matureAfterWater = Math.max(0, matureLeft - currentWaterReduce)
    const fastestLeft = matureAfterWater * 4 / 5
    const fastestEta = new Date(now.getTime() + Math.ceil(fastestLeft * 60) * 1000)
    const calculationResult: CalculationResult = { matureLeft, waterLeftInput, elapsedSinceLastWater, currentWaterReduce, matureAfterWater, fastestLeft, fastestEta }
    void calculationInput
    void calculationResult

    result.value = `【${crop.name} · ${TIME_MODE_LABELS[timeMode.value]}】\n距上次浇水：${formatMinutes(elapsedSinceLastWater)}\n本次可减少：${formatMinutes(currentWaterReduce)}\n浇水后剩余：${formatMinutes(matureAfterWater)}\n\n理论最快还需：${formatMinutes(fastestLeft)}\n预计成熟：${formatDateTime(fastestEta)}`
    nextTick(() => resultPanel.value?.scrollTo({ top: 0, behavior: 'smooth' }))
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
  error.value = ''
  result.value = '填写成熟时间和水分时间后点击“计算”。\n\n开启自动跳转时，最后一格输入两位数字会自动计算。'
  nextTick(() => matureHourInput.value?.focus())
}

function clearError(): void {
  error.value = ''
}

function selectCrop(crop: CropConfig): void {
  cropName.value = crop.name
  showCropMenu.value = false
  clearError()
  nextTick(() => matureHourInput.value?.focus())
}

function cycleCrop(step = 1): void {
  const currentIndex = crops.findIndex((crop) => crop.name === cropName.value)
  cropName.value = crops[(currentIndex + step + crops.length) % crops.length].name
  clearError()
}

function cycleTimeMode(): void {
  timeMode.value = isClockMode.value ? TIME_MODE_COUNTDOWN : TIME_MODE_CLOCK
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

function handleInputEnter(event: NumericKeyboardEvent, nextRef: MaybeInputRef): void {
  event.preventDefault()
  const nextInput = resolveInputElement(nextRef)
  if (nextInput) {
    focusAndSelectInput(nextInput)
    return
  }
  calculate()
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

function maxForInput(input: HTMLInputElement): number | null {
  if (input === matureHourInput.value) return matureHourMax.value
  if (input === matureMinuteInput.value) return 59
  if (input === waterHourInput.value) return waterHourMax.value
  if (input === waterMinuteInput.value) return 59
  return null
}

function shouldAutoAdvance(value: string, maxValue: number): boolean {
  return value !== '' && (value.length >= String(maxValue).length || Number(value) * 10 > maxValue)
}

function advanceIfInputIsComplete(input: HTMLInputElement, maxValue: number, nextRef: MaybeInputRef): void {
  if (!autoAdvance.value) return
  const nextInput = resolveInputElement(nextRef)
  if (!nextInput || !shouldAutoAdvance(input.value.trim(), maxValue)) return
  scheduleFocusInput(nextInput)
}

function scheduleAutomaticCalculation(): void {
  if (!autoAdvance.value || autoCalculateQueued) return
  autoCalculateQueued = true
  nextTick(() => {
    autoCalculateQueued = false
    if (autoAdvance.value && waterMinute.value.trim().length >= 2) calculate()
  })
}

function routeOverflowDigit(event: NumericKeyboardEvent, maxValue: number, nextRef: MaybeInputRef): void {
  if (!autoAdvance.value) return
  const digit = event.key
  if (!/^\d$/.test(digit)) return
  routeOverflowText(event, digit, maxValue, nextRef)
}

function routeOverflowBeforeInput(event: NumericInputBeforeEvent, maxValue: number, nextRef: MaybeInputRef): void {
  if (!autoAdvance.value) return
  const inputText = event.data ?? ''
  if (event.inputType !== 'insertText' || !/^\d$/.test(inputText)) return
  routeOverflowText(event, inputText, maxValue, nextRef)
}

function routeOverflowText(event: NumericKeyboardEvent | NumericInputBeforeEvent, text: string, maxValue: number, nextRef: MaybeInputRef): void {
  if (!isHtmlInputElement(event.target)) return
  const input = event.target
  const nextInput = resolveInputElement(nextRef)
  if (!nextInput) return

  const start = input.selectionStart ?? input.value.length
  const end = input.selectionEnd ?? input.value.length
  const proposed = `${input.value.slice(0, start)}${text}${input.value.slice(end)}`
  if (proposed === '') return
  if (Number(proposed) <= maxValue) {
    if (shouldAutoAdvance(proposed, maxValue)) scheduleFocusInput(nextInput)
    return
  }

  event.preventDefault()
  focusAndSelectInput(nextInput)

  const nextMax = maxForInput(nextInput)
  const nextProposed = `${nextInput.value}${text}`
  if (nextMax === null || Number(nextProposed) > nextMax) return
  setInputModel(nextInput, nextProposed)
  nextTick(() => {
    nextInput.value = nextProposed
    advanceIfInputIsComplete(nextInput, nextMax, orderedInputElements()[orderedInputElements().indexOf(nextInput) + 1])
  })
}

function sanitizeNumber(event: NumericInputEvent, _modelValue: string, maxValue: number, nextRef: MaybeInputRef = null, calculateWhenComplete = false): void {
  if (!isHtmlInputElement(event.target)) return
  const cleaned = event.target.value.replace(/\D/g, '').slice(0, 2)
  const normalized = cleaned === '' ? '' : Number(cleaned) > maxValue ? String(maxValue) : cleaned
  setInputModel(event.target, normalized)
  event.target.value = normalized
  advanceIfInputIsComplete(event.target, maxValue, nextRef)
  if (calculateWhenComplete && cleaned.length >= 2) scheduleAutomaticCalculation()
}

function handleGlobalKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && (showCropMenu.value || showSettings.value)) {
    event.preventDefault()
    showCropMenu.value = false
    showSettings.value = false
    return
  }
  if (showCropMenu.value || showSettings.value) return
  if (event.altKey && event.key.toLowerCase() === 'x') {
    event.preventDefault()
    cycleTimeMode()
    return
  }
  if (event.key === 'Tab') {
    event.preventDefault()
    cycleCrop(event.shiftKey ? -1 : 1)
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
      <button class="header-icon-button" type="button" aria-label="打开设置" @click="showSettings = true">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 8.4a3.6 3.6 0 1 0 0 7.2 3.6 3.6 0 0 0 0-7.2Zm9 3.6-2.05-1.18c.05-.34.05-.66 0-1L21 8.64l-2-3.46-2.06 1.18a8.3 8.3 0 0 0-.86-.5V3.5h-4v2.36c-.3.14-.59.31-.86.5L9.16 5.18l-2 3.46 2.05 1.18a7.3 7.3 0 0 0 0 1L7.16 12l2 3.46 2.06-1.18c.27.19.56.36.86.5v2.36h4v-2.36c.3-.14.59-.31.86-.5L19 15.46 21 12Z" />
        </svg>
      </button>
    </header>

    <main class="app-main">
      <div class="page-shell">
        <section class="calculator-grid">
          <form id="calculator-form" class="panel input-panel" @submit.prevent="calculate">
            <div class="input-toolbar">
              <div>
                <strong>输入参数</strong>
                <small>作物类型指完整生长周期</small>
              </div>
              <button
                class="time-mode-switch"
                :class="{ 'is-clock': isClockMode }"
                type="button"
                :aria-label="`当前为${TIME_MODE_LABELS[timeMode]}，点击切换`"
                @click="cycleTimeMode"
              >
                <span class="switch-thumb" aria-hidden="true"></span>
                <span :class="{ active: !isClockMode }">倒计时</span>
                <span :class="{ active: isClockMode }">具体时间</span>
              </button>
            </div>

            <div v-if="isClockMode" class="date-control">
              <span>成熟日期</span>
              <div v-if="needsManualDay" class="day-toggle" aria-label="选择成熟日期">
                <button type="button" :class="{ active: clockDay === CLOCK_DAY_TODAY }" @click="clockDay = CLOCK_DAY_TODAY">今日</button>
                <button type="button" :class="{ active: clockDay === CLOCK_DAY_TOMORROW }" @click="clockDay = CLOCK_DAY_TOMORROW">明日</button>
              </div>
              <strong v-else class="auto-day">{{ clockAutoDay }}</strong>
            </div>

            <div class="time-row">
              <span class="row-label">{{ isClockMode ? '预计成熟' : '成熟剩余' }}</span>
              <div class="time-input-group">
                <input ref="matureHourInput" v-model="matureHour" maxlength="2" inputmode="numeric" autocomplete="off" aria-label="成熟时间小时" @beforeinput="routeOverflowBeforeInput($event, matureHourMax, matureMinuteInput)" @keydown="routeOverflowDigit($event, matureHourMax, matureMinuteInput)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter="handleInputEnter($event, matureMinuteInput)" @input="sanitizeNumber($event, matureHour, matureHourMax, matureMinuteInput)" />
                <span>{{ isClockMode ? '点' : '时' }}</span>
                <input ref="matureMinuteInput" v-model="matureMinute" maxlength="2" inputmode="numeric" autocomplete="off" aria-label="成熟时间分钟" @beforeinput="routeOverflowBeforeInput($event, 59, waterHourInput)" @keydown="routeOverflowDigit($event, 59, waterHourInput)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter="handleInputEnter($event, waterHourInput)" @input="sanitizeNumber($event, matureMinute, 59, waterHourInput)" />
                <span>分</span>
              </div>
            </div>

            <div class="time-row">
              <span class="row-label">水分剩余</span>
              <div class="time-input-group">
                <input ref="waterHourInput" v-model="waterHour" maxlength="2" inputmode="numeric" autocomplete="off" aria-label="水分剩余小时" @beforeinput="routeOverflowBeforeInput($event, waterHourMax, waterMinuteInput)" @keydown="routeOverflowDigit($event, waterHourMax, waterMinuteInput)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter="handleInputEnter($event, waterMinuteInput)" @input="sanitizeNumber($event, waterHour, waterHourMax, waterMinuteInput)" />
                <span>时</span>
                <input ref="waterMinuteInput" v-model="waterMinute" maxlength="2" inputmode="numeric" autocomplete="off" aria-label="水分剩余分钟" @beforeinput="routeOverflowBeforeInput($event, 59, null)" @keydown="routeOverflowDigit($event, 59, null)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter="handleInputEnter($event, null)" @input="sanitizeNumber($event, waterMinute, 59, null, true)" />
                <span>分</span>
              </div>
            </div>

            <p class="reference">{{ referenceText }}</p>
          </form>

          <aside ref="resultPanel" class="panel result-panel">
            <div class="result-heading">
              <strong>计算结果</strong>
              <span>{{ currentCrop.shortName }}</span>
            </div>
            <div v-if="error" class="error-box">{{ error }}</div>
            <pre>{{ result }}</pre>
          </aside>
        </section>
      </div>
    </main>

    <footer class="app-footer">
      <button class="footer-button secondary" type="button" @click="clearInputs">清空</button>
      <button class="footer-button crop-button" type="button" aria-haspopup="dialog" @click="showCropMenu = true">
        <span>{{ currentCrop.shortName }}</span>
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 7.5 5 5 5-5" /></svg>
      </button>
      <button class="footer-button primary" type="submit" form="calculator-form">计算</button>
    </footer>

    <div v-if="showCropMenu" class="modal-backdrop" role="presentation" @click.self="showCropMenu = false">
      <section class="modal-card crop-menu" role="dialog" aria-modal="true" aria-labelledby="crop-menu-title">
        <div class="modal-heading">
          <div>
            <strong id="crop-menu-title">选择作物类型</strong>
            <small>按完整成熟周期选择</small>
          </div>
          <button class="modal-close" type="button" aria-label="关闭" @click="showCropMenu = false">×</button>
        </div>
        <div class="crop-options">
          <button v-for="crop in crops" :key="crop.name" type="button" :class="{ selected: crop.name === cropName }" @click="selectCrop(crop)">
            <span>{{ crop.name }}</span>
            <small>水分上限 {{ formatMinutes(crop.waterMaxMinutes) }}</small>
            <span class="check" aria-hidden="true">✓</span>
          </button>
        </div>
      </section>
    </div>

    <div v-if="showSettings" class="modal-backdrop" role="presentation" @click.self="showSettings = false">
      <section class="modal-card settings-card" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div class="modal-heading">
          <div>
            <strong id="settings-title">输入设置</strong>
            <small>控制数字输入后的焦点行为</small>
          </div>
          <button class="modal-close" type="button" aria-label="关闭" @click="showSettings = false">×</button>
        </div>
        <button class="setting-row" type="button" role="switch" :aria-checked="autoAdvance" @click="autoAdvance = !autoAdvance">
          <span>
            <strong>自动跳到下一格</strong>
            <small>{{ autoAdvance ? '输入达到有效位数后自动跳转；最后一格输入两位后自动计算。' : '不自动跳转；按回车进入下一格，最后一格回车计算。' }}</small>
          </span>
          <span class="setting-switch" :class="{ active: autoAdvance }"><i></i></span>
        </button>
        <button class="done-button" type="button" @click="showSettings = false">完成</button>
      </section>
    </div>
  </div>
</template>
