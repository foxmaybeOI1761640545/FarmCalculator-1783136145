"""Tkinter 版农场成熟计算器。

本文件保留桌面 GUI 的原始计算流程，使用分钟作为主要业务单位，并用
Fraction 表示浇水减少、理论最快成熟等可能出现分数分钟的中间值，避免
浮点误差影响最终向上取整的展示结果。界面负责输入校验、焦点导航、
快捷键和倒计时/具体时间两种成熟时间读法。
"""

from __future__ import annotations
import json
import math
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

@dataclass(frozen=True)
class CropType:
    """作物类型配置。

    name 是界面展示名称；base_minutes 是基础成熟时长（分钟）；water_max_minutes
    是当前水分最多还能维持的时长（分钟）。属性方法基于这两个固定参数派生
    满额浇水减少和理论最快成熟时间，供说明文案与 calculate() 共用。
    """
    name: str
    base_minutes: int
    water_max_minutes: int

    @property
    def full_water_reduce_minutes(self) -> Fraction:
        """返回满额浇水本次可减少的成熟时间，单位为分钟。

        公式为水分最大维持时间的四分之一；使用 Fraction 是为了保留精确比例，
        避免 8/16/32 小时作物在展示秒级结果前提前丢失精度。
        """
        return Fraction(self.water_max_minutes, 4)

    @property
    def fresh_auto_water_mature_left_minutes(self) -> Fraction:
        """返回新种植并立即满额浇水后的成熟剩余分钟数。"""
        return Fraction(self.base_minutes, 1) - self.full_water_reduce_minutes

    @property
    def fresh_auto_water_fastest_minutes(self) -> Fraction:
        """返回新作物后续按理论最快操作时仍需的分钟数。"""
        return self.fresh_auto_water_mature_left_minutes * Fraction(4, 5)

# 固定作物表：键名与下拉框显示值一致，计算时通过当前选项直接索引。
CROPS = {
    "8小时作物": CropType("8小时作物", 8*60, 2*60+40),
    "16小时作物": CropType("16小时作物", 16*60, 5*60+20),
    "32小时作物": CropType("32小时作物", 32*60, 10*60+40),
}

class InputError(ValueError):
    """带有目标输入框的用户输入错误。

    calculate() 捕获该异常后会弹出错误消息，并把焦点恢复到 entry，方便用户
    直接修正对应字段；entry 为 None 时只展示错误而不移动焦点。
    """
    def __init__(self, message: str, entry: ttk.Entry | None = None):
        """保存错误文案和应当聚焦的 Tk Entry。"""
        super().__init__(message)
        self.entry = entry

def ceil_fraction(value: Fraction | int | float) -> int:
    """对正数向上取整，非正数按 0 返回。

    value 可为 Fraction、int 或 float；计算剩余时间时使用该函数把分数分钟转换
    为秒级展示，确保不会因向下取整低估成熟时间。
    """
    if not isinstance(value, Fraction):
        value = Fraction(value)
    if value <= 0:
        return 0
    return (value.numerator + value.denominator - 1) // value.denominator

def format_minutes(minutes: Fraction | int | float) -> str:
    """将分钟数格式化为中文时长。

    输入单位是分钟，可包含 Fraction 小数；函数先换算为秒并向上取整，再组合
    “小时/分钟/秒”，用于错误提示、参考说明和计算结果。
    """
    if not isinstance(minutes, Fraction):
        minutes = Fraction(minutes)
    total_seconds = ceil_fraction(minutes * 60)
    if total_seconds <= 0: return "0分钟"
    hours, rem = divmod(total_seconds, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if hours: parts.append(f"{hours}小时")
    if mins: parts.append(f"{mins}分钟")
    if secs: parts.append(f"{secs}秒")
    return "".join(parts)

def read_non_negative_int(entry: ttk.Entry, field_name: str) -> int:
    """从 Entry 读取非负整数，空字符串按 0 处理。

    field_name 用于生成用户可读错误；当文本包含非数字字符时抛出 InputError，
    并携带原 Entry 供调用方恢复焦点。
    """
    text = entry.get().strip()
    if text == "":
        return 0
    if not re.fullmatch(r"\d+", text):
        raise InputError(f"{field_name} 只能输入非负整数。", entry)
    return int(text)

def read_minute(entry: ttk.Entry, field_name: str) -> int:
    """读取分钟字段并校验范围为 0–59。

    该函数复用 read_non_negative_int 的非负整数校验，额外阻止 60 及以上分钟，
    因为小时进位必须由用户显式输入。
    """
    value = read_non_negative_int(entry, field_name)
    if value >= 60:
        raise InputError(f"{field_name} 必须在 0-59 之间。", entry)
    return value

class FarmCalculator(tk.Tk):
    """桌面版成熟计算器主窗口。

    类继承 tk.Tk，负责构建所有 Tkinter 控件、保存控件变量、绑定快捷键、
    维护输入焦点和执行成熟时间计算。业务时间统一以分钟为单位；配置文件只
    持久化成熟时间输入模式，不保存用户输入值。
    """
    WINDOW_WIDTH = 1120
    WINDOW_HEIGHT = 390
    BACKSPACE_CLEAR_PRESS_COUNT = 3
    BACKSPACE_CLEAR_WINDOW_SECONDS = 0.8
    TIME_MODE_COUNTDOWN = "countdown"
    TIME_MODE_CLOCK = "clock"
    TIME_MODE_LABELS = {
        TIME_MODE_COUNTDOWN: "倒计时",
        TIME_MODE_CLOCK: "具体时间",
    }
    CLOCK_DAY_TODAY = "今日"
    CLOCK_DAY_TOMORROW = "明日"
    CLOCK_DAY_OPTIONS = (CLOCK_DAY_TODAY, CLOCK_DAY_TOMORROW)
    CONFIG_PATH = Path.home() / ".farm_calculator_config.json"

    def __init__(self):
        """初始化窗口、响应式变量、输入校验命令和首屏焦点。"""
        super().__init__()
        self.title("王者荣耀农场最快成熟时间计算器")
        self._center_window(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self.resizable(False, False)
        self.configure(bg="#F5F5F5")
        self.crop_order = list(CROPS.keys())
        self.crop_var = tk.StringVar(value="16小时作物")
        self.time_mode_var = tk.StringVar(value=self._load_time_mode())
        self.clock_day_var = tk.StringVar(value=self.CLOCK_DAY_TODAY)
        self.int_validate_cmd = (self.register(self._validate_int_text), "%P", "%W")
        self._backspace_press_times: list[float] = []
        self._build_ui()
        self._bind_global_shortcuts()
        self._update_reference_text()
        self.after(100, self._focus_first_input)


    def _load_time_mode(self) -> str:
        """从用户主目录配置文件读取成熟时间输入模式。

        读取失败、JSON 损坏或值不在已知模式内时回退到倒计时，避免启动失败。
        """
        try:
            with self.CONFIG_PATH.open("r", encoding="utf-8") as file:
                config = json.load(file)
        except (OSError, json.JSONDecodeError):
            return self.TIME_MODE_COUNTDOWN

        time_mode = config.get("time_mode")
        if time_mode in self.TIME_MODE_LABELS:
            return time_mode
        return self.TIME_MODE_COUNTDOWN

    def _save_time_mode(self) -> None:
        """把当前时间模式写入 JSON 配置文件。

        I/O 失败时静默忽略，因为该偏好不影响核心计算。
        """
        config = {"time_mode": self.time_mode_var.get()}
        try:
            with self.CONFIG_PATH.open("w", encoding="utf-8") as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
        except OSError:
            # 保存偏好失败不影响计算器本身使用。
            pass

    def _handle_time_mode_change(self) -> None:
        """处理模式切换：持久化设置、刷新相关控件并回到第一个输入框。"""
        self._save_time_mode()
        self._update_time_mode_ui()
        self._focus_first_input()

    def _update_time_mode_ui(self) -> None:
        """根据倒计时/具体时间模式切换标签、单位和日期控件可见性。"""
        if self.time_mode_var.get() == self.TIME_MODE_CLOCK:
            self.mature_time_label.config(text="预计成熟时间：")
            self.mature_h_unit_label.config(text="点")
            self.mature_m_unit_label.config(text="分成熟")
            self._update_clock_day_visibility()
            self._update_clock_day_auto_text()
        else:
            self.mature_time_label.config(text="当前成熟剩余：")
            self.mature_h_unit_label.config(text="小时")
            self.mature_m_unit_label.config(text="分钟后成熟")
            self.clock_day_label.place_forget()
            self.clock_day_box.place_forget()
            self.clock_day_auto_label.place_forget()

    def _read_mature_left(self, now: datetime, crop: CropType) -> Fraction:
        """读取并换算当前成熟剩余时间。

        倒计时模式直接把小时和分钟合并为分钟；具体时间模式使用 now 作为同一
        计算周期的时间基准，8/16 小时作物自动选择今日或明日，32 小时作物按
        用户选择的今日/明日严格判断。无效输入会抛出 InputError。
        """
        if self.time_mode_var.get() == self.TIME_MODE_CLOCK:
            mature_hour = read_non_negative_int(self.mature_h_entry, "预计成熟时间小时")
            mature_minute = read_minute(self.mature_m_entry, "预计成熟时间分钟")
            if mature_hour >= 24:
                raise InputError("预计成熟时间小时必须在 0-23 之间。", self.mature_h_entry)

            today_time = now.replace(hour=mature_hour, minute=mature_minute, second=0, microsecond=0)
            tomorrow_time = today_time + timedelta(days=1)
            if crop.base_minutes >= 32 * 60:
                day_choice = self.clock_day_var.get()
                if day_choice == self.CLOCK_DAY_TODAY:
                    if today_time <= now:
                        raise InputError(
                            "具体时间输入有误：已选择“今日”，但该时刻已经过去。请改选“明日”或输入晚于当前时间的今日时刻。",
                            self.mature_h_entry,
                        )
                    return self._clock_delta_minutes(now, today_time)
                return self._clock_delta_minutes(now, tomorrow_time)

            target_time = today_time if today_time > now else tomorrow_time
            return self._clock_delta_minutes(now, target_time)

        mature_h = read_non_negative_int(self.mature_h_entry, "当前成熟剩余小时")
        mature_m = read_minute(self.mature_m_entry, "当前成熟剩余分钟")
        return Fraction(mature_h * 60 + mature_m)

    def _clock_delta_minutes(self, now: datetime, target: datetime) -> Fraction:
        """返回 now 到 target 的向上取整分钟差，负值按 0 处理。"""
        seconds = max(0, (target - now).total_seconds())
        return Fraction(math.ceil(seconds / 60))

    def _update_clock_day_visibility(self) -> None:
        """刷新具体时间模式下日期选择或自动日期提示的显示状态。"""
        if self.time_mode_var.get() != self.TIME_MODE_CLOCK:
            self.clock_day_label.place_forget()
            self.clock_day_box.place_forget()
            self.clock_day_auto_label.place_forget()
            return

        if self._current_crop().base_minutes >= 32 * 60:
            self.clock_day_auto_label.place_forget()
            self.clock_day_label.place(x=430, y=110, width=50)
            self.clock_day_box.place(x=485, y=110)
        else:
            self.clock_day_label.place_forget()
            self.clock_day_box.place_forget()
            self.clock_day_auto_label.place(x=430, y=110, width=180)
            self._update_clock_day_auto_text()

    def _update_clock_day_auto_text(self) -> None:
        """为 8/16 小时作物显示根据当前时刻推断的今日/明日。

        输入为空、非数字或越界时显示未知，避免在用户尚未完成输入时给出误导。
        """
        if self.time_mode_var.get() != self.TIME_MODE_CLOCK or self._current_crop().base_minutes >= 32 * 60:
            return
        hour_text = self.mature_h_entry.get().strip()
        minute_text = self.mature_m_entry.get().strip()
        if not hour_text.isdigit() or not minute_text.isdigit():
            self.clock_day_auto_label.config(text="日期：--")
            return
        hour = int(hour_text)
        minute = int(minute_text)
        if hour >= 24 or minute >= 60:
            self.clock_day_auto_label.config(text="日期：--")
            return
        now = datetime.now()
        today_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        day_text = self.CLOCK_DAY_TODAY if today_time > now else self.CLOCK_DAY_TOMORROW
        self.clock_day_auto_label.config(text=f"日期：{day_text}")

    def _center_window(self, width: int, height: int) -> None:
        """按屏幕尺寸把固定大小窗口居中显示。"""
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self):
        """创建窗口标题、提示、输入区和结果区。"""
        ttk.Label(self, text="王者荣耀农场最快成熟时间计算器",
                  font=("Microsoft YaHei UI", 17, "bold"), background="#F5F5F5").place(x=22, y=20)
        ttk.Label(self, text="注意：作物类型指 8/16/32 小时作物，不是当前还剩几小时成熟。",
                  foreground="#555555", background="#F5F5F5").place(x=22, y=55)
        self._build_input_area()
        self._build_result_area()

    def _build_input_area(self):
        """创建左侧输入区。

        包括作物选择、时间模式、成熟时间、水分剩余、计算/清空按钮和参考说明；
        同时绑定回车导航与自动跳转。
        """
        frame = tk.Frame(self, bg="#FFFFFF", bd=1, relief="solid")
        frame.place(x=22, y=90, width=710, height=280)
        # 左侧标题
        ttk.Label(frame, text="输入参数", font=("Microsoft YaHei UI", 11, "bold"), foreground="#0066CC",
                  background="#FFFFFF").place(x=10, y=10)
        # 作物类型
        ttk.Label(frame, text="作物类型：", anchor="e", justify="right", background="#FFFFFF").place(x=20, y=40, width=120)
        self.crop_box = ttk.Combobox(frame, textvariable=self.crop_var, values=self.crop_order, state="readonly", width=16)
        self.crop_box.place(x=150, y=40)
        self.crop_box.bind("<<ComboboxSelected>>", self._handle_crop_change)
        self.crop_box.bind("<Return>", lambda _event: self._focus_entry(self.mature_h_entry))
        # 成熟时间输入模式
        ttk.Label(frame, text="成熟时间输入：", anchor="e", justify="right", background="#FFFFFF").place(x=20, y=75, width=120)
        ttk.Radiobutton(frame, text="显示倒计时", variable=self.time_mode_var, value=self.TIME_MODE_COUNTDOWN,
                        command=self._handle_time_mode_change).place(x=150, y=75)
        ttk.Radiobutton(frame, text="显示具体时间", variable=self.time_mode_var, value=self.TIME_MODE_CLOCK,
                        command=self._handle_time_mode_change).place(x=270, y=75)
        self.clock_day_label = ttk.Label(frame, text="日期：", anchor="e", justify="right", background="#FFFFFF")
        self.clock_day_box = ttk.Combobox(frame, textvariable=self.clock_day_var, values=self.CLOCK_DAY_OPTIONS,
                                          state="readonly", width=10)
        self.clock_day_auto_label = ttk.Label(frame, text="日期：--", background="#FFFFFF")
        # 当前成熟时间
        self.mature_time_label = ttk.Label(frame, text="", anchor="e", justify="right", background="#FFFFFF")
        self.mature_time_label.place(x=20, y=110, width=120)
        self.mature_h_entry = self._create_number_entry(frame)
        self.mature_h_entry.place(x=150, y=110)
        self.mature_h_unit_label = ttk.Label(frame, text="", background="#FFFFFF")
        self.mature_h_unit_label.place(x=250, y=110)
        self.mature_m_entry = self._create_number_entry(frame)
        self.mature_m_entry.place(x=290, y=110)
        self.mature_m_unit_label = ttk.Label(frame, text="", background="#FFFFFF")
        self.mature_m_unit_label.place(x=360, y=110)
        # 当前水分还能维持
        ttk.Label(frame, text="当前水分还能维持：", anchor="e", justify="right", background="#FFFFFF").place(x=20, y=145, width=120)
        self.water_h_entry = self._create_number_entry(frame)
        self.water_h_entry.place(x=150, y=145)
        ttk.Label(frame, text="小时", background="#FFFFFF").place(x=250, y=145)
        self.water_m_entry = self._create_number_entry(frame)
        self.water_m_entry.place(x=290, y=145)
        ttk.Label(frame, text="分钟", background="#FFFFFF").place(x=360, y=145)
        self.input_entries = [self.mature_h_entry, self.mature_m_entry, self.water_h_entry, self.water_m_entry]
        self._bind_entry_navigation()

        # 按钮
        calc_btn = ttk.Button(frame, text="🧮 计算", command=self.calculate, width=12)
        clear_btn = ttk.Button(frame, text="🗑 清空", command=self.clear_inputs, width=12)
        calc_btn.place(x=150, y=185)
        clear_btn.place(x=290, y=185)
        # 说明
        self.reference_label = ttk.Label(frame, text="", foreground="#555555", wraplength=660, justify="left", background="#FFFFFF")
        self.reference_label.place(x=20, y=225)
        self._update_time_mode_ui()
        # 回车切换
        self.mature_h_entry.bind("<Return>", lambda _e: self._focus_entry(self.mature_m_entry))
        self.mature_m_entry.bind("<Return>", lambda _e: self._focus_entry(self.water_h_entry))
        self.water_h_entry.bind("<Return>", lambda _e: self._focus_entry(self.water_m_entry))
        self.water_m_entry.bind("<Return>", lambda _e: self.calculate())
        self._bind_auto_advance()

    def _build_result_area(self):
        """创建右侧结果区，初始展示操作提示。"""
        frame = tk.Frame(self, bg="#FFFFFF", bd=1, relief="solid")
        frame.place(x=760, y=90, width=330, height=280)
        ttk.Label(frame, text="计算结果", font=("Microsoft YaHei UI", 12, "bold"),
                  foreground="#228B22", background="#FFFFFF").place(x=10, y=10)
        self.result_label = tk.Label(frame, text="请输入数据后点击\"计算\"按钮计算；\n\n或者在最后一个输入框按回车计算；\n\n计算结果将会显示在这里。",
                                     font=("Microsoft YaHei UI", 10), wraplength=310, justify="left",
                                     background="#E8F5E9", anchor="nw")
        self.result_label.place(x=10, y=40, width=310, height=230)

    def _create_number_entry(self, parent: tk.Widget) -> ttk.Entry:
        """创建带 key 级整数校验的居中输入框。"""
        return ttk.Entry(parent, width=8, justify="center", validate="key", validatecommand=self.int_validate_cmd)

    def _validate_int_text(self, new_text: str, widget_name: str) -> bool:
        """Tk validatecommand 回调，只允许空字符串或未超过当前字段上限的数字。

        widget_name 来自 Tk 的 %W；解析失败时放行，避免校验回调自身导致控件异常。
        """
        if not re.fullmatch(r"\d*", new_text):
            return False
        if new_text == "":
            return True
        try:
            widget = self.nametowidget(widget_name)
        except KeyError:
            return True
        if not isinstance(widget, ttk.Entry):
            return True
        max_value = self._entry_max_value(widget)
        if max_value is None:
            return True
        return int(new_text) <= max_value

    def _bind_global_shortcuts(self) -> None:
        """安装全局快捷键 bindtag。

        Tab/Shift+Tab 循环作物，Ctrl+Tab 切换时间模式，连续 Backspace 清空。
        这些绑定放在自定义 bindtag 中，以便优先于默认控件焦点移动。
        """
        # Tab 用于在 8 / 16 / 32 小时作物之间循环切换。
        # 这里不用直接 bind_all("<ISO_Left_Tab>")，因为部分 Windows/Tk 版本不认识这个键名，
        # 会在启动时抛出 TclError: bad event type or keysym "ISO_Left_Tab"。
        shortcut_tag = "FarmCalculatorShortcut"
        self._install_shortcut_bindtag(self, shortcut_tag)
        self.bind_class(shortcut_tag, "<Tab>", lambda _event: self._cycle_crop_type(1))
        self.bind_class(shortcut_tag, "<Shift-Tab>", lambda _event: self._cycle_crop_type(-1))
        self.bind_class(shortcut_tag, "<Control-Tab>", lambda _event: self._cycle_time_mode())
        self.bind_class(shortcut_tag, "<Control-Shift-Tab>", lambda _event: self._cycle_time_mode())
        self.bind_class(shortcut_tag, "<BackSpace>", self._handle_backspace_clear_shortcut)

        # 某些 Linux/Tk 环境会把 Shift+Tab 识别成 ISO_Left_Tab；支持就绑定，不支持就跳过。
        try:
            self.bind_class(shortcut_tag, "<ISO_Left_Tab>", lambda _event: self._cycle_crop_type(-1))
        except tk.TclError:
            pass

    def _install_shortcut_bindtag(self, widget: tk.Widget, shortcut_tag: str) -> None:
        """递归给窗口及子控件安装快捷键 bindtag。"""
        # 把自定义 bindtag 放在默认控件行为之前，确保 Tab 不会先被 Entry/Button 拿去移动焦点。
        tags = widget.bindtags()
        if shortcut_tag not in tags:
            widget.bindtags((shortcut_tag, *tags))
        for child in widget.winfo_children():
            self._install_shortcut_bindtag(child, shortcut_tag)

    def _bind_entry_navigation(self) -> None:
        """绑定方向键在四个输入框之间移动焦点。"""
        for entry in self.input_entries:
            entry.bind("<Up>", self._focus_previous_input)
            entry.bind("<Left>", self._focus_previous_input)
            entry.bind("<Down>", self._focus_next_input)
            entry.bind("<Right>", self._focus_next_input)

    def _bind_auto_advance(self) -> None:
        """绑定数字输入的溢出路由与输入完整自动跳转。"""
        for entry in self.input_entries:
            entry.bind("<KeyPress>", self._route_overflow_digit, add="+")
            entry.bind("<KeyRelease>", self._handle_auto_advance, add="+")

    def _route_overflow_digit(self, event: tk.Event) -> str | None:
        """在继续输入会超过当前字段上限时，把数字转交给下一个输入框。

        返回 "break" 表示阻止 Tk 默认插入；返回 None 时保留默认输入行为。
        """
        if event.char not in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            return None
        entry = event.widget
        if not isinstance(entry, ttk.Entry):
            return None
        text = entry.get().strip()
        if not text.isdigit():
            return None
        max_value = self._entry_max_value(entry)
        next_entry = self._next_input(entry)
        if max_value is None or next_entry is None:
            return None
        proposed_text = f"{text}{event.char}"
        if int(proposed_text) <= max_value:
            return None

        self._focus_entry(next_entry)
        if self._validate_int_text(f"{next_entry.get().strip()}{event.char}", str(next_entry)):
            next_entry.insert(tk.END, event.char)
            self._update_clock_day_auto_text()
            self._advance_if_input_is_complete(next_entry)
        return "break"

    def _handle_auto_advance(self, event: tk.Event) -> None:
        """KeyRelease 后更新日期提示，并在当前数字已完整时安排焦点跳转。"""
        if event.keysym not in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            return
        entry = event.widget
        if not isinstance(entry, ttk.Entry):
            return
        self._update_clock_day_auto_text()
        self._advance_if_input_is_complete(entry)

    def _advance_if_input_is_complete(self, entry: ttk.Entry) -> None:
        """判断当前输入是否无需等待下一位，若完整则跳到下一输入框。

        判定规则基于字段最大值：达到最大位数，或继续追加一位必然超过最大值时，
        认为当前值已经完整。
        """
        text = entry.get().strip()
        if not text.isdigit():
            return
        max_value = self._entry_max_value(entry)
        if max_value is None:
            return

        # key 校验已经阻止超限；这里只负责在“继续输入必然超限”时立即切到下一框。
        if len(text) >= len(str(max_value)) or int(text) * 10 > max_value:
            next_entry = self._next_input(entry)
            if next_entry is not None:
                self.after(1, lambda target=next_entry: self._focus_entry(target))

    def _entry_max_value(self, entry: ttk.Entry) -> int | None:
        """返回指定输入框当前允许的最大整数值；未知控件返回 None。"""
        crop = self._current_crop()
        if entry is self.mature_h_entry:
            if self.time_mode_var.get() == self.TIME_MODE_CLOCK:
                return 23
            return crop.base_minutes // 60
        if entry is self.mature_m_entry:
            return 59
        if entry is self.water_h_entry:
            return crop.water_max_minutes // 60
        if entry is self.water_m_entry:
            return 59
        return None

    def _next_input(self, entry: ttk.Entry) -> ttk.Entry | None:
        """按输入顺序返回下一个 Entry；最后一个或未知控件返回 None。"""
        try:
            index = self.input_entries.index(entry)
        except ValueError:
            return None
        next_index = index + 1
        if next_index >= len(self.input_entries):
            return None
        return self.input_entries[next_index]

    def _focus_entry(self, entry: ttk.Entry) -> str:
        """聚焦并全选指定输入框，返回 break 供事件绑定阻止默认行为。"""
        entry.focus_set()
        entry.selection_range(0, tk.END)
        return "break"

    def _focus_error_entry(self, entry: ttk.Entry | None) -> None:
        """错误弹窗关闭后把焦点恢复到出错输入框。"""
        if entry is None:
            return
        self.lift()
        self.focus_force()
        entry.focus_force()
        entry.selection_range(0, tk.END)

    def _focus_first_input(self) -> str:
        """聚焦第一个成熟小时输入框，用于启动、清空和模式切换后恢复输入。"""
        # 窗口打开后把输入焦点放到第一个文本框。
        # focus_force 可减少 Windows 上启动后焦点仍停留在命令行窗口的问题。
        self.mature_h_entry.focus_force()
        self.mature_h_entry.selection_range(0, tk.END)
        return "break"

    def _focus_previous_input(self, event: tk.Event) -> str:
        """方向键回到上一个输入框；第一个输入框保持在自身。"""
        try:
            index = self.input_entries.index(event.widget)
        except ValueError:
            return "break"
        previous_index = max(0, index - 1)
        return self._focus_entry(self.input_entries[previous_index])

    def _focus_next_input(self, event: tk.Event) -> str:
        """方向键前往下一个输入框；最后一个输入框阻止默认移动。"""
        next_entry = self._next_input(event.widget)
        if next_entry is None:
            return "break"
        return self._focus_entry(next_entry)

    def _cycle_time_mode(self) -> str:
        """在倒计时和具体时间之间循环切换，并复用统一模式变更处理。"""
        if self.time_mode_var.get() == self.TIME_MODE_CLOCK:
            self.time_mode_var.set(self.TIME_MODE_COUNTDOWN)
        else:
            self.time_mode_var.set(self.TIME_MODE_CLOCK)
        self._handle_time_mode_change()
        return "break"

    def _handle_crop_change(self, _event: tk.Event | None = None) -> None:
        """作物变化后刷新参考文案、日期控件和自动日期提示。"""
        self._update_reference_text()
        self._update_clock_day_visibility()
        self._update_clock_day_auto_text()

    def _cycle_crop_type(self, step: int = 1) -> str:
        """按 step 在 8/16/32 小时作物之间循环，返回 break 阻止默认 Tab 行为。"""
        current = self.crop_var.get()
        try:
            index = self.crop_order.index(current)
        except ValueError:
            index = 0
        next_index = (index + step) % len(self.crop_order)
        self.crop_var.set(self.crop_order[next_index])
        self._handle_crop_change()
        return "break"

    def _handle_backspace_clear_shortcut(self, event: tk.Event) -> str | None:
        """统计短时间内 Backspace 次数，达到阈值时清空全部输入。

        前两次返回 None，保留输入框删除字符的默认行为；第三次返回 "break"。
        """
        now = time.monotonic()
        window_start = now - self.BACKSPACE_CLEAR_WINDOW_SECONDS
        self._backspace_press_times = [t for t in self._backspace_press_times if t >= window_start]
        self._backspace_press_times.append(now)

        if len(self._backspace_press_times) >= self.BACKSPACE_CLEAR_PRESS_COUNT:
            self._backspace_press_times.clear()
            self.clear_inputs()
            return "break"

        # 前两次 Backspace 保留控件默认行为，仍可正常删除输入框里的字符。
        return None

    def _current_crop(self) -> CropType:
        """返回当前下拉框选中的作物配置。"""
        return CROPS[self.crop_var.get()]

    def _update_reference_text(self):
        """根据当前作物刷新底部参考说明。"""
        crop = self._current_crop()
        text = (f"当前按【{crop.name}】计算：基础成熟 {format_minutes(crop.base_minutes)}；"
                f"水分最大维持 {format_minutes(crop.water_max_minutes)}；"
                f"满额浇水减少 {format_minutes(crop.full_water_reduce_minutes)}；"
                f"一键种植并自动浇水后，理论最快成熟时间 "
                f"{format_minutes(crop.fresh_auto_water_fastest_minutes)}。")
        self.reference_label.config(text=text)

    def clear_inputs(self):
        """清空四个输入框、结果提示和 Backspace 计数，并恢复首个输入焦点。"""
        self._backspace_press_times.clear()
        for entry in [self.mature_h_entry, self.mature_m_entry, self.water_h_entry, self.water_m_entry]:
            entry.delete(0, tk.END)
        self.result_label.config(text="请输入数据后点击计算。\n\n也可以在最后一个输入框按回车计算。")
        self._focus_first_input()

    def calculate(self):
        """执行成熟时间计算并更新结果区。

        计算阶段依次为：读取原始成熟剩余 mature_left；读取水分剩余并推导距上次
        浇水 elapsed_since_last_water；按已消耗水分的四分之一计算本次可减少
        current_water_reduce；得到浇水后剩余 mature_after_water；再乘以 4/5 得到
        后续理论最快剩余 fastest_left；最后用 now + fastest_left 生成预计最快成熟
        时间。所有业务量使用分钟，异常由本方法捕获并转换为消息框。
        """
        try:
            crop = self._current_crop()
            now = datetime.now()
            mature_left = self._read_mature_left(now, crop)
            water_h = read_non_negative_int(self.water_h_entry, "当前水分剩余小时")
            water_m = read_minute(self.water_m_entry, "当前水分剩余分钟")

            water_left_input = Fraction(water_h * 60 + water_m)

            if mature_left <= 0:
                raise InputError("当前成熟剩余时间必须大于 0。", self.mature_h_entry)

            if mature_left > Fraction(crop.base_minutes):
                if self.time_mode_var.get() == self.TIME_MODE_CLOCK:
                    raise InputError(
                        f"具体时间输入有误：该时刻换算后还需 {format_minutes(mature_left)}，"
                        f"已超过【{crop.name}】的基础成熟时间 {format_minutes(crop.base_minutes)}。"
                        "请检查作物类型、成熟日期或输入的时分。",
                        self.mature_h_entry,
                    )
                raise InputError(
                    f"当前成熟剩余时间不能超过【{crop.name}】的基础成熟时间："
                    f"{format_minutes(crop.base_minutes)}。",
                    self.mature_h_entry,
                )

            if water_left_input > Fraction(crop.water_max_minutes):
                raise InputError(
                    f"当前水分还能维持时间不能超过【{crop.name}】的最大水分维持时间："
                    f"{format_minutes(crop.water_max_minutes)}。",
                    self.water_h_entry,
                )

            water_left = water_left_input

            # 全程使用 Fraction，避免 int / float 混用导致最快成熟时间计算时报错。
            elapsed_since_last_water = max(
                Fraction(0),
                min(Fraction(crop.water_max_minutes), Fraction(crop.water_max_minutes) - water_left),
            )
            current_water_reduce = min(mature_left, elapsed_since_last_water / 4)
            mature_after_water = max(Fraction(0), mature_left - current_water_reduce)
            fastest_left = mature_after_water * Fraction(4, 5)
            fastest_eta = now + timedelta(seconds=ceil_fraction(fastest_left * 60))
            time_mode_label = self.TIME_MODE_LABELS.get(self.time_mode_var.get(), "倒计时")

            result = (f"当前按【{crop.name}】计算（成熟时间输入：{time_mode_label}）\n\n"
                      f"距上次浇水：{format_minutes(elapsed_since_last_water)}\n"
                      f"本次可减少：{format_minutes(current_water_reduce)}\n"
                      f"浇水后剩余：{format_minutes(mature_after_water)}\n\n"
                      f"理论最快还需：{format_minutes(fastest_left)}\n"
                      f"预计最快成熟时间：\n{fastest_eta.strftime('%Y-%m-%d %H:%M:%S')}")
            self.result_label.config(text=result)
        except InputError as exc:
            messagebox.showerror("输入错误", str(exc))
            self.after(50, lambda entry=exc.entry: self._focus_error_entry(entry))
        except ValueError as exc:
            messagebox.showerror("输入错误", str(exc))
            self.after(50, lambda: self._focus_error_entry(self.focus_get() if isinstance(self.focus_get(), ttk.Entry) else self.mature_h_entry))
        except Exception as exc:
            messagebox.showerror("计算失败", f"计算过程中发生错误：\n{exc}")
            self.after(50, self._focus_first_input)
        return "break"

if __name__ == "__main__":
    app = FarmCalculator()
    app.mainloop()