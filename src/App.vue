<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch, type Ref } from 'vue'

type TimeMode = 'countdown' | 'clock'
type ClockDay = '今日' | '明日'

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
type NumericInputBeforeEvent = InputEvent

const TIME_MODE_COUNTDOWN: TimeMode = 'countdown'
const TIME_MODE_CLOCK: TimeMode = 'clock'
const TIME_MODE_LABELS: Record<TimeMode, string> = {
  [TIME_MODE_COUNTDOWN]: '倒计时',
  [TIME_MODE_CLOCK]: '具体时间',
}
const CLOCK_DAY_TODAY: ClockDay = '今日'
const CLOCK_DAY_TOMORROW: ClockDay = '明日'
const STORAGE_KEY = 'farm-calculator-time-mode'
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
const matureHourInput = ref<HTMLInputElement | null>(null)
const matureMinuteInput = ref<HTMLInputElement | null>(null)
const waterHourInput = ref<HTMLInputElement | null>(null)
const waterMinuteInput = ref<HTMLInputElement | null>(null)

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
  return `当前按【${crop.name}】计算：基础成熟 ${formatMinutes(crop.baseMinutes)}；水分最大维持 ${formatMinutes(crop.waterMaxMinutes)}；满额浇水减少 ${formatMinutes(crop.waterMaxMinutes / 4)}；一键种植并自动浇水后，理论最快成熟时间 ${formatMinutes((crop.baseMinutes - crop.waterMaxMinutes / 4) * 4 / 5)}。`
})
const matureHourMax = computed(() => isClockMode.value ? 23 : currentCrop.value.baseMinutes / 60)
const waterHourMax = computed(() => Math.floor(currentCrop.value.waterMaxMinutes / 60))

onMounted(() => {
  const savedMode = localStorage.getItem(STORAGE_KEY)
  if (savedMode === TIME_MODE_COUNTDOWN || savedMode === TIME_MODE_CLOCK) timeMode.value = savedMode
  nextTick(() => matureHourInput.value?.focus())
})

watch(timeMode, (mode) => {
  localStorage.setItem(STORAGE_KEY, mode)
  clearError()
  nextTick(() => matureHourInput.value?.focus())
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
    scrollToBottomOnMobile()
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
  result.value = '请输入数据后点击计算。\n\n也可以在最后一个输入框按回车计算。'
  nextTick(() => matureHourInput.value?.focus())
}

function clearError(): void {
  error.value = ''
}

function cycleCrop(step = 1): void {
  const currentIndex = crops.findIndex((crop) => crop.name === cropName.value)
  cropName.value = crops[(currentIndex + step + crops.length) % crops.length].name
}

function cycleTimeMode(): void {
  timeMode.value = isClockMode.value ? TIME_MODE_COUNTDOWN : TIME_MODE_CLOCK
}

function scrollToBottomOnMobile(): void {
  if (!window.matchMedia('(max-width: 780px)').matches) return
  nextTick(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' })
  })
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
  const nextInput = resolveInputElement(nextRef)
  if (!nextInput || !shouldAutoAdvance(input.value.trim(), maxValue)) return
  scheduleFocusInput(nextInput)
}

function routeOverflowDigit(event: NumericKeyboardEvent, maxValue: number, nextRef: MaybeInputRef): void {
  const digit = event.key
  if (!/^\d$/.test(digit)) return
  routeOverflowText(event, digit, maxValue, nextRef)
}

function routeOverflowBeforeInput(event: NumericInputBeforeEvent, maxValue: number, nextRef: MaybeInputRef): void {
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

function sanitizeNumber(event: NumericInputEvent, _modelValue: string, maxValue: number, nextRef: MaybeInputRef = null): void {
  if (!isHtmlInputElement(event.target)) return
  const cleaned = event.target.value.replace(/\D/g, '')
  const normalized = cleaned === '' ? '' : String(Math.min(Number(cleaned), maxValue))
  setInputModel(event.target, normalized)
  event.target.value = normalized
  advanceIfInputIsComplete(event.target, maxValue, nextRef)
}

function handleGlobalKeydown(event: KeyboardEvent): void {
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
  <main class="page-shell" @keydown="handleGlobalKeydown">
    <section class="hero-card">
      <p class="eyebrow">Honor of Kings Farm Tool</p>
      <h1><span class="desktop-title">王者荣耀农场最快成熟时间计算器</span><span class="mobile-title">王者荣耀农场<br />理论最快成熟时间<br />计算器</span></h1>
      <p class="subtitle">注意：作物类型指 8/16/32 小时作物，不是当前还剩几小时成熟。</p>
    </section>

    <section class="calculator-grid">
      <form class="panel input-panel" @submit.prevent="calculate">
        <div class="panel-heading">
          <span>输入参数</span>
          <small class="desktop-shortcuts">Tab 切换作物，Alt+X 切换时间模式，连续 3 次 Backspace 清空</small>
          <small class="mobile-clear-hint">连续 3 次删除可清空所有输入，并回到第一个输入框</small>
        </div>

        <label class="field full">
          <span>作物类型</span>
          <select v-model="cropName" @change="clearError">
            <option v-for="crop in crops" :key="crop.name" :value="crop.name">{{ crop.name }}</option>
          </select>
        </label>

        <div class="field full">
          <span>成熟时间输入</span>
          <div class="segmented">
            <label><input v-model="timeMode" type="radio" :value="TIME_MODE_COUNTDOWN" /> 显示倒计时</label>
            <label><input v-model="timeMode" type="radio" :value="TIME_MODE_CLOCK" /> 显示具体时间</label>
          </div>
        </div>

        <div v-if="needsManualDay" class="field full compact-row">
          <span>日期</span>
          <select v-model="clockDay">
            <option>{{ CLOCK_DAY_TODAY }}</option>
            <option>{{ CLOCK_DAY_TOMORROW }}</option>
          </select>
        </div>
        <p v-else-if="isClockMode" class="date-hint">日期：{{ clockAutoDay }}</p>

        <div class="time-row">
          <span class="row-label">{{ isClockMode ? '预计成熟时间' : '当前成熟剩余' }}</span>
          <input ref="matureHourInput" v-model="matureHour" inputmode="numeric" autocomplete="off" @beforeinput="routeOverflowBeforeInput($event, matureHourMax, matureMinuteInput)" @keydown="routeOverflowDigit($event, matureHourMax, matureMinuteInput)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="focusAdjacentInput($event, 1)" @input="sanitizeNumber($event, matureHour, matureHourMax, matureMinuteInput)" />
          <span class="unit-label">{{ isClockMode ? '点' : '小时' }}</span>
          <input ref="matureMinuteInput" v-model="matureMinute" inputmode="numeric" autocomplete="off" @beforeinput="routeOverflowBeforeInput($event, 59, waterHourInput)" @keydown="routeOverflowDigit($event, 59, waterHourInput)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="focusAdjacentInput($event, 1)" @input="sanitizeNumber($event, matureMinute, 59, waterHourInput)" />
          <span class="unit-label suffix-label">{{ isClockMode ? '分成熟' : '分钟后成熟' }}</span>
        </div>

        <div class="time-row">
          <span class="row-label">当前水分还能维持</span>
          <input ref="waterHourInput" v-model="waterHour" inputmode="numeric" autocomplete="off" @beforeinput="routeOverflowBeforeInput($event, waterHourMax, waterMinuteInput)" @keydown="routeOverflowDigit($event, waterHourMax, waterMinuteInput)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="focusAdjacentInput($event, 1)" @input="sanitizeNumber($event, waterHour, waterHourMax, waterMinuteInput)" />
          <span class="unit-label">小时</span>
          <input ref="waterMinuteInput" v-model="waterMinute" inputmode="numeric" autocomplete="off" @beforeinput="routeOverflowBeforeInput($event, 59, null)" @keydown="routeOverflowDigit($event, 59, null)" @keydown.up.prevent="focusAdjacentInput($event, -1)" @keydown.left.prevent="focusAdjacentInput($event, -1)" @keydown.down.prevent="focusAdjacentInput($event, 1)" @keydown.right.prevent="focusAdjacentInput($event, 1)" @keydown.enter.prevent="calculate" @input="sanitizeNumber($event, waterMinute, 59)" />
          <span class="unit-label suffix-label">分钟</span>
        </div>

        <div class="actions">
          <button class="primary" type="submit">🧮 计算</button>
          <button type="button" @click="clearInputs">🗑 清空</button>
        </div>

        <p class="reference">{{ referenceText }}</p>
      </form>

      <aside class="panel result-panel">
        <div class="panel-heading success"><span>计算结果</span></div>
        <div v-if="error" class="error-box">{{ error }}</div>
        <pre>{{ result }}</pre>
      </aside>
    </section>
  </main>
</template>
