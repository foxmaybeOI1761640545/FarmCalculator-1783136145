<script setup lang="ts">
import { App as CapacitorApp } from '@capacitor/app'
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'

type TimeMode = 'countdown' | 'clock'
type ClockDay = '今日' | '明日'
type DialogName = 'crop' | 'settings' | 'autoAdvanceHelp'

/**
 * 作物配置。所有时间均以分钟为单位，供输入上限、参考文案和成熟公式共用。
 */
interface CropConfig {
  name: string
  baseMinutes: number
  waterMaxMinutes: number
}

/**
 * 单次成功计算的快照。
 *
 * 作物名称和模式文案在计算时固化，避免用户随后切换作物或模式导致旧结果标题变化。
 * 所有时间量字段均为分钟；fastestEta 保存实际 Date 以便模板同时生成可读文本和 datetime 属性。
 */
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

/**
 * 自动跳转决策结果。
 *
 * shouldAdvance 表示当前输入是否已经是完整值；resolvedDay 仅用于 32 小时具体时间模式，
 * 当今日/明日只有一个日期可行时由输入流程应用，避免在 computed/watch 中产生副作用。
 */
interface AutoAdvanceDecision {
  shouldAdvance: boolean
  resolvedDay?: ClockDay
}

type InputRef = Ref<HTMLInputElement | null>
type MaybeInputRef = InputRef | HTMLInputElement | null
type NumericInputEvent = Event
type NumericKeyboardEvent = KeyboardEvent

/** 时间模式、日期选项和 localStorage 键。字符串值会持久化，修改会影响旧用户配置兼容性。 */
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

/** 三种农场作物的固定业务参数。baseMinutes 是基础成熟时长，waterMaxMinutes 是水分最长维持时长。 */
const crops: CropConfig[] = [
  { name: '8小时作物', baseMinutes: 8 * 60, waterMaxMinutes: 2 * 60 + 40 },
  { name: '16小时作物', baseMinutes: 16 * 60, waterMaxMinutes: 5 * 60 + 20 },
  { name: '32小时作物', baseMinutes: 32 * 60, waterMaxMinutes: 10 * 60 + 40 },
]

/**
 * 页面核心响应式状态。
 *
 * 输入框状态均保存为字符串，便于区分空字符串、用户正在输入的前缀和已完成数字；
 * 解析与校验集中在 read* 函数和 sanitizeNumber 中。
 */
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

/** 当前作物配置；当 cropName 异常时回退到 16 小时作物，避免计算流程拿到 undefined。 */
const currentCrop = computed(() => crops.find((crop) => crop.name === cropName.value) ?? crops[1])
/** 底部作物按钮显示的短文案，去掉“作物”以节省移动端底栏宽度。 */
const cropButtonText = computed(() => currentCrop.value.name.replace('作物', ''))
/** 是否处于具体时间模式；多个日期判断和输入单位显示依赖该布尔值。 */
const isClockMode = computed(() => timeMode.value === TIME_MODE_CLOCK)
/** 32 小时作物在具体时间模式下可能跨两天，必须由用户或自动跳转决策明确今日/明日。 */
const needsManualDay = computed(() => isClockMode.value && currentCrop.value.baseMinutes >= 32 * 60)
/**
 * 8/16 小时具体时间模式的自动日期提示。
 *
 * 该 computed 只负责展示推断，不写入 clockDay；输入不完整或越界时返回 “--”。
 */
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
/** 根据当前作物生成参考说明，帮助用户核对基础成熟、水分维持和理论最快时长。 */
const referenceText = computed(() => {
  const crop = currentCrop.value
  return `基础成熟 ${formatMinutes(crop.baseMinutes)}；水分最大维持 ${formatMinutes(crop.waterMaxMinutes)}；满额浇水减少 ${formatMinutes(crop.waterMaxMinutes / 4)}；理论最快 ${formatMinutes((crop.baseMinutes - crop.waterMaxMinutes / 4) * 4 / 5)}。`
})
/** 成熟小时输入上限：具体时间固定 23，倒计时跟随当前作物基础小时数。 */
const matureHourMax = computed(() => isClockMode.value ? 23 : currentCrop.value.baseMinutes / 60)
/** 水分小时输入上限，等于当前作物最大水分维持分钟数向下取整为小时。 */
const waterHourMax = computed(() => Math.floor(currentCrop.value.waterMaxMinutes / 60))

let removeBackButtonListener: (() => void) | undefined

/**
 * 组件挂载后恢复本地偏好、注册 Android 返回键并聚焦首个输入框。
 *
 * Capacitor backButton 与 Esc/遮罩共用 closeDialog，保证弹窗关闭顺序一致。
 */
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

/** 组件卸载时移除 Capacitor 返回键监听，避免 WebView 生命周期重建后重复注册。 */
onUnmounted(() => {
  removeBackButtonListener?.()
})

/** 时间模式变化后持久化到 localStorage，并重置错误与自动计算去重标记。 */
watch(timeMode, (mode) => {
  localStorage.setItem(STORAGE_KEY, mode)
  clearError()
  lastAutoCalculatedWaterMinute.value = ''
  nextTick(() => matureHourInput.value?.focus())
})

/** 自动跳转设置变化后立即写入 localStorage；同时清除最后一分钟自动计算去重状态。 */
watch(autoAdvanceEnabled, (enabled) => {
  localStorage.setItem(AUTO_ADVANCE_STORAGE_KEY, String(enabled))
  lastAutoCalculatedWaterMinute.value = ''
})

/** 水分分钟被用户改成新值后允许下一次两位合法分钟再次触发自动计算。 */
watch(waterMinute, (value) => {
  if (value !== lastAutoCalculatedWaterMinute.value) lastAutoCalculatedWaterMinute.value = ''
})

/**
 * 将可选数字字符串解析为整数。
 *
 * 空字符串在日期预览中按 0 处理；非数字返回 null，让调用方显示未知状态而不是抛错。
 * @param value 输入框字符串。
 * @returns 解析后的整数，或表示非法数字的 null。
 */
function toOptionalInteger(value: string): number | null {
  const text = String(value ?? '').trim()
  if (text === '') return 0
  if (!/^\d+$/.test(text)) return null
  return Number(text)
}

/**
 * 从输入字符串读取非负整数。
 *
 * 空字符串按 0 处理，这是为了允许用户只填写小时或分钟的一部分；非数字会抛出面向用户的错误。
 * @param value 输入框字符串。
 * @param fieldName 错误消息中展示的字段名。
 * @throws 当 value 不是空字符串且不是纯数字时抛出 Error。
 */
function readNonNegativeInt(value: string, fieldName: string): number {
  const text = String(value ?? '').trim()
  if (text === '') return 0
  if (!/^\d+$/.test(text)) throw new Error(`${fieldName} 只能输入非负整数。`)
  return Number(text)
}

/**
 * 读取分钟字段并限制在 0–59。
 * @throws 当分钟大于等于 60 或包含非数字字符时抛出 Error。
 */
function readMinute(value: string, fieldName: string): number {
  const minute = readNonNegativeInt(value, fieldName)
  if (minute >= 60) throw new Error(`${fieldName} 必须在 0-59 之间。`)
  return minute
}

/**
 * 将正数向上取整，非正数统一归零。
 *
 * 用于分钟/秒展示，避免小数分钟在显示时被向下取整导致低估剩余时间。
 */
function ceilPositive(value: number): number {
  if (value <= 0) return 0
  return Math.ceil(value)
}

/**
 * 将分钟数格式化为中文时长。
 *
 * 输入单位是分钟，可为小数；内部转换为秒并向上取整，保证理论计算中的分数分钟仍完整展示。
 */
function formatMinutes(minutes: number): string {
  const totalSeconds = ceilPositive(minutes * 60)
  if (totalSeconds <= 0) return '0分钟'
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60
  return [hours ? `${hours}小时` : '', mins ? `${mins}分钟` : '', secs ? `${secs}秒` : ''].join('')
}

/**
 * 将 Date 格式化为 yyyy-MM-dd HH:mm:ss。
 *
 * 展示精度保持到秒，和 fastestEta 的秒级取整策略一致。
 */
function formatDateTime(date: Date): string {
  const pad = (num: number): string => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/**
 * 根据当前输入模式读取“当前距离成熟还剩多少分钟”。
 *
 * 倒计时模式直接读取小时/分钟；具体时间模式根据当前日期、自动今日/明日逻辑或 32 小时作物的手动日期计算差值。
 * @param now 同一次计算的时间基准，避免跨秒/跨分钟重复创建 Date 导致结果不一致。
 * @param crop 当前作物配置，用于 32 小时日期规则和上限错误提示。
 * @throws 当具体时间已过去、小时越界或输入非数字时抛出 Error，由 calculate 捕获展示。
 */
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

/**
 * 计算 now 到 target 的分钟差，并向上取整。
 *
 * 负差值归零；具体时间模式使用该函数统一 Date 到分钟的口径。
 */
function clockDeltaMinutes(now: Date, target: Date): number {
  return Math.ceil(Math.max(0, target.getTime() - now.getTime()) / 60000)
}

/**
 * 计算某个候选“小时:分钟 + 今日/明日”距离成熟的分钟数。
 *
 * 该函数只做时间差，不做业务有效性判断；调用方需再检查 0 < matureLeft <= 作物基础成熟时长。
 */
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

/**
 * 为自动跳转决策读取成熟分钟的当前状态。
 * @returns undefined 表示分钟为空、需要扫描 00–59；null 表示分钟非法；number 表示可用的精确分钟。
 */
function minuteDecisionValue(): number | null | undefined {
  const text = matureMinute.value.trim()
  if (text === '') return undefined
  if (!/^\d+$/.test(text)) return null
  const minute = Number(text)
  return minute >= 0 && minute <= 59 ? minute : null
}

/**
 * 判断指定日期下某个小时是否存在有效成熟分钟。
 *
 * minute 为 undefined 时扫描 00–59；为 null 时直接无效；为 number 时只验证精确分钟。
 */
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

/**
 * 枚举某个日期下所有可作为成熟时间的小时值。
 *
 * 返回值供前缀可延伸性判断使用，确保“2”是否等待“20–23”取决于真实成熟窗口。
 */
function validClockHourValues(now: Date, crop: CropConfig, day: ClockDay, minute: number | null | undefined = undefined): number[] {
  const values = new Set<number>()
  for (let hour = 0; hour <= 23; hour += 1) {
    if (clockHourHasValidMinute(now, crop, hour, day, minute)) values.add(hour)
  }
  return [...values].sort((left, right) => left - right)
}

/** 合并多个小时集合并排序，用于今日/明日并集前缀判断。 */
function mergeUniqueHours(...hourLists: number[][]): number[] {
  return [...new Set(hourLists.flat())].sort((left, right) => left - right)
}

/**
 * 判断当前小时前缀是否还能延伸成更长有效小时。
 *
 * 若存在以该前缀开头的两位有效小时，自动跳转必须等待用户继续输入。
 */
function hasLongerHourWithPrefix(prefix: string, allowedHours: number[]): boolean {
  return allowedHours.some((hour) => {
    const text = String(hour)
    return text.length > prefix.length && text.startsWith(prefix)
  })
}

/**
 * 为 32 小时作物具体时间模式生成小时输入决策。
 *
 * 分别检查今日和明日是否可行：仅一边可行时返回 resolvedDay；两边都可行时尊重用户当前选择；两边都不可行时不跳转。
 */
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

/**
 * 判断成熟小时输入是否完整。
 *
 * 倒计时按作物最大小时判断；具体时间按真实有效成熟窗口判断；自动跳转关闭时始终不产生副作用。
 */
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

/**
 * 所有输入框自动跳转的统一入口。
 *
 * 成熟小时走日期/前缀决策，其他输入框沿用最大值与下一位是否必然超限的规则。
 */
function decideAutoAdvance(value: string, maxValue: number, input: HTMLInputElement, now = new Date()): AutoAdvanceDecision {
  if (!autoAdvanceEnabled.value || value === '') return { shouldAdvance: false }
  if (input === matureHourInput.value) return decideMatureHourAutoAdvance(value, now)
  return { shouldAdvance: Number(value) <= maxValue && (value.length >= String(maxValue).length || Number(value) * 10 > maxValue) }
}

/**
 * 执行核心成熟时间计算并写入结构化结果。
 *
 * 公式阶段依次为：原始成熟剩余、水分已消耗、本次可减少、浇水后剩余、理论最快剩余、理论总计可节省和预计最快成熟时间。
 * 所有业务错误在此捕获并写入 error，模板据此切换错误/成功/空状态。
 */
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

/** 清空所有输入、错误、成功结果和自动计算去重状态，并把焦点恢复到第一个输入框。 */
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

/** 清除当前错误消息；通常在用户修改模式、日期或作物后调用。 */
function clearError(): void {
  error.value = ''
}

/** 键盘快捷键使用的时间模式切换函数，在倒计时和具体时间之间循环。 */
function cycleTimeMode(): void {
  timeMode.value = isClockMode.value ? TIME_MODE_COUNTDOWN : TIME_MODE_CLOCK
}

/** 设置成熟时间输入模式，触发 watcher 持久化并刷新首个输入焦点。 */
function setTimeMode(mode: TimeMode): void {
  timeMode.value = mode
}

/** 设置 32 小时具体时间模式的今日/明日选择，并清除旧错误。 */
function setClockDay(day: ClockDay): void {
  clockDay.value = day
  clearError()
}

/** 从作物弹窗选择作物，不清空用户输入，只刷新当前作物状态并关闭弹窗。 */
function setCrop(crop: CropConfig): void {
  cropName.value = crop.name
  clearError()
  closeDialog()
}

/**
 * 打开指定弹窗并管理焦点来源。
 *
 * 设置弹窗进入帮助弹窗时不覆盖 lastFocusedElement，因此关闭帮助先回到设置，再关闭设置才回到顶部设置按钮。
 */
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

/** 返回指定弹窗是否为当前活动弹窗，供 aria-expanded 使用并避免模板类型窄化问题。 */
function isDialogOpen(dialogName: DialogName): boolean {
  return activeDialog.value === dialogName
}

/** 根据 activeDialog 返回当前弹窗根元素，用于初始聚焦和焦点陷阱。 */
function currentDialogElement(): HTMLElement | null {
  if (activeDialog.value === 'crop') return cropDialog.value
  if (activeDialog.value === 'settings') return settingsDialog.value
  if (activeDialog.value === 'autoAdvanceHelp') return autoAdvanceHelpDialog.value
  return null
}

/** 收集弹窗内可聚焦元素，过滤 disabled 和 tabindex=-1，供 Tab 焦点循环使用。 */
function focusableDialogElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>('button, input, [href], [tabindex]:not([tabindex="-1"])'))
    .filter((element) => !element.hasAttribute('disabled') && element.tabIndex !== -1)
}

/** 弹窗打开后将焦点移入第一个可聚焦控件；若没有控件则聚焦弹窗本身。 */
function focusActiveDialog(): void {
  nextTick(() => {
    const dialog = currentDialogElement()
    if (!dialog) return
    const firstFocusable = focusableDialogElements(dialog)[0]
    ;(firstFocusable ?? dialog).focus()
  })
}

/**
 * 关闭当前弹窗并恢复焦点。
 *
 * 帮助弹窗是设置弹窗的二级弹窗：关闭帮助只返回设置并聚焦问号按钮；其他弹窗关闭到背景并恢复打开前焦点。
 */
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

/** 在弹窗内循环 Tab/Shift+Tab，防止键盘焦点落到背景页面。 */
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

/** 统一处理弹窗内 Esc 和 Tab；Esc 与遮罩、Android 返回键共用 closeDialog。 */
function handleDialogKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeDialog()
    return
  }
  if (event.key === 'Tab') trapDialogFocus(event)
}

/** 类型守卫：确认事件目标或 ref 值是真实 HTMLInputElement。 */
function isHtmlInputElement(value: EventTarget | HTMLInputElement | null): value is HTMLInputElement {
  return typeof HTMLInputElement !== 'undefined' && value instanceof HTMLInputElement
}

/** 返回四个数字输入框的当前 DOM 顺序，供方向键和 Enter 导航使用。 */
function orderedInputElements(): HTMLInputElement[] {
  return [matureHourInput.value, matureMinuteInput.value, waterHourInput.value, waterMinuteInput.value].filter(isHtmlInputElement)
}

/** 根据方向键在相邻输入框之间移动焦点，并全选目标内容。 */
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

/** 同时支持 ref 对象和直接 DOM 节点，解析出可聚焦输入框。 */
function resolveInputElement(inputRef: MaybeInputRef): HTMLInputElement | null {
  if (!inputRef) return null
  if (typeof HTMLInputElement !== 'undefined' && inputRef instanceof HTMLInputElement) return inputRef
  const candidate: unknown = inputRef.value
  if (isHtmlInputElement(candidate as EventTarget | HTMLInputElement | null)) return candidate as HTMLInputElement
  return null
}

/** 聚焦输入框并全选文本，方便用户连续覆盖输入。 */
function focusAndSelectInput(input: HTMLInputElement): void {
  input.focus()
  input.select()
}

/** 在自动跳转开启时延迟聚焦下一项，等待 Vue 完成 v-model 和 DOM 同步。 */
function scheduleFocusInput(input: HTMLInputElement): void {
  if (!autoAdvanceEnabled.value) return
  nextTick(() => {
    setTimeout(() => focusAndSelectInput(input), 0)
  })
}

/** 根据输入框 DOM 节点反写对应的字符串状态；sanitizeNumber 的唯一状态写入口。 */
function setInputModel(input: HTMLInputElement, value: string): void {
  if (input === matureHourInput.value) matureHour.value = value
  if (input === matureMinuteInput.value) matureMinute.value = value
  if (input === waterHourInput.value) waterHour.value = value
  if (input === waterMinuteInput.value) waterMinute.value = value
}

/**
 * 在用户输入后根据自动跳转决策移动到下一输入框。
 *
 * 对成熟小时会先应用唯一可行的今日/明日决策，再调度焦点；其他输入框只处理焦点。
 */
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

/**
 * 数字输入的统一清洗入口。
 *
 * 删除非数字、限制最大值、同步 v-model，并在真实 input 事件后触发自动跳转或最后分钟自动计算。
 */
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

/**
 * 水分分钟输入两位合法数字 00–59 后自动计算一次。
 *
 * rawValue 保留用户原始两位输入，isOverMax 防止 60–99 被 clamp 成 59 后误触发。
 */
function maybeAutoCalculateFromWaterMinute(rawValue: string, isOverMax: boolean): void {
  if (!autoAdvanceEnabled.value || isOverMax) return
  if (!/^\d{2}$/.test(rawValue) || Number(rawValue) > 59) return
  if (rawValue === lastAutoCalculatedWaterMinute.value) return
  lastAutoCalculatedWaterMinute.value = rawValue
  calculate()
}

/** Enter 键导航：前三个输入框前往下一项，最后一个输入框执行 calculate。 */
function handleInputEnter(event: NumericKeyboardEvent, nextRef: MaybeInputRef = null): void {
  event.preventDefault()
  const nextInput = resolveInputElement(nextRef)
  if (nextInput) focusAndSelectInput(nextInput)
  else calculate()
}

/**
 * 全局键盘入口。
 *
 * 弹窗打开时 Esc 优先关闭弹窗；背景状态下支持 Alt+X 切换模式和连续 Backspace 清空。
 */
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
    <!-- 顶部栏：固定标题与设置入口。 -->
    <header class="app-header">
      <h1>成熟计算器</h1>
      <button class="icon-button" type="button" aria-label="打开设置" @click="openDialog('settings')">⚙️</button>
    </header>

    <main class="app-main">
      <div class="page-shell">
        <p class="notice-card">作物类型是 8/16/32 小时作物，不是当前剩余成熟时间。</p>

        <!-- 输入区：时间模式、成熟时间、水分剩余与作物参考说明。 -->
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

        <!-- 结果区：空状态、错误状态和结构化成功结果共用同一固定卡片。 -->
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

    <!-- 底部栏：清空、作物选择和表单提交三个主要操作。 -->
    <footer class="app-footer">
      <button class="footer-button secondary" type="button" @click="clearInputs">清空</button>
      <button class="footer-button crop-button" type="button" aria-haspopup="dialog" :aria-expanded="activeDialog === 'crop'" @click="openDialog('crop')">{{ cropButtonText }}</button>
      <button class="footer-button primary" type="submit" form="calculator-form">计算</button>
    </footer>

    <!-- 弹窗区：Teleport 到 body，避免受 App Shell overflow 限制。 -->
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
