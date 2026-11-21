#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; keyboard_strategy.ahk
; 键位改造方案：Caps Lock 双功能 + Vim 风格符号层
; ============================================================

; ===== 配置参数 =====
global TAP_TERM := 200          ; Tap/Hold 分界时间（ms）
global DEBUG_MODE := false      ; 调试模式，显示 ToolTip

; ===== Esc → CapsLock（大小写锁定） =====
; 原始 Esc 键位置改为 CapsLock 功能
$Esc::CapsLock

; ===== Caps Lock 双功能 =====
; Tap: Esc  |  Hold: Ctrl

CapsLock::
{
    capsDownTime := A_TickCount
    Send("{LCtrl down}")
    KeyWait("CapsLock")
    Send("{LCtrl up}")

    ; 如果按住时间 < tap_term 且没有其他键被按下，则触发 Esc
    if (A_PriorKey = "CapsLock" && (A_TickCount - capsDownTime) < TAP_TERM) {
        Send("{Esc}")
    }

    if (DEBUG_MODE) {
        ToolTip("CapsLock released, prior: " . A_PriorKey . ", duration: " . (A_TickCount - capsDownTime) . "ms")
        SetTimer(() => ToolTip(), -1000)
    }
}

; ===== 符号层 =====
; 空格 Tap: 空格  |  空格 Hold: 激活符号层

; 状态变量
global spaceHeld := false
global symbolLayerActive := false
global symbolTriggered := false

; 空格键按下：启动延迟定时器
Space::
{
    global spaceHeld, symbolTriggered
    spaceHeld := true
    symbolTriggered := false
    SetTimer(CheckSpaceHold, -TAP_TERM)
}

; 延迟定时器：超过 tap_term 仍未松开，激活符号层
CheckSpaceHold()
{
    global spaceHeld, symbolLayerActive
    if (spaceHeld) {
        symbolLayerActive := true
        if (DEBUG_MODE) {
            ToolTip("Symbol layer ACTIVATED")
            SetTimer(() => ToolTip(), -1000)
        }
    }
}

; 空格键松开：判断 Tap/Hold
Space up::
{
    global spaceHeld, symbolLayerActive, symbolTriggered

    if (!symbolTriggered && !symbolLayerActive) {
        ; Tap：发送空格
        Send("{Space}")
    }
    ; Hold 但未触发符号：什么都不发

    spaceHeld := false
    symbolLayerActive := false
}

; ===== 符号层映射（Vim 风格） =====
; 按住空格 + 按键 = 符号

; --- Home Row 左手 ---
#HotIf symbolLayerActive
a:: {
    global symbolTriggered
    symbolTriggered := true
    Send("@")
}

s:: {
    global symbolTriggered
    symbolTriggered := true
    Send("{#}")
}

d:: {
    global symbolTriggered
    symbolTriggered := true
    Send("_")
}

f:: {
    global symbolTriggered
    symbolTriggered := true
    Send("-")
}

g:: {
    global symbolTriggered
    symbolTriggered := true
    Send("=")
}

; --- Home Row 右手 ---
h:: {
    global symbolTriggered
    symbolTriggered := true
    Send("{{}")
}

j:: {
    global symbolTriggered
    symbolTriggered := true
    Send("{}}")
}

k:: {
    global symbolTriggered
    symbolTriggered := true
    Send("[")
}

l:: {
    global symbolTriggered
    symbolTriggered := true
    Send("]")
}

SC027:: {
    global symbolTriggered
    symbolTriggered := true
    Send(":")
}

; --- Top Row（数字层） ---
q:: {
    global symbolTriggered
    symbolTriggered := true
    Send("1")
}

w:: {
    global symbolTriggered
    symbolTriggered := true
    Send("2")
}

e:: {
    global symbolTriggered
    symbolTriggered := true
    Send("3")
}

r:: {
    global symbolTriggered
    symbolTriggered := true
    Send("4")
}

t:: {
    global symbolTriggered
    symbolTriggered := true
    Send("5")
}

y:: {
    global symbolTriggered
    symbolTriggered := true
    Send("6")
}

u:: {
    global symbolTriggered
    symbolTriggered := true
    Send("7")
}

i:: {
    global symbolTriggered
    symbolTriggered := true
    Send("8")
}

o:: {
    global symbolTriggered
    symbolTriggered := true
    Send("9")
}

p:: {
    global symbolTriggered
    symbolTriggered := true
    Send("0")
}

; --- Bottom Row ---
z:: {
    global symbolTriggered
    symbolTriggered := true
    Send("{!}")
}

x:: {
    global symbolTriggered
    symbolTriggered := true
    Send("{%}")
}

c:: {
    global symbolTriggered
    symbolTriggered := true
    Send("(")
}

v:: {
    global symbolTriggered
    symbolTriggered := true
    Send(")")
}

b:: {
    global symbolTriggered
    symbolTriggered := true
    Send("\")
}

n:: {
    global symbolTriggered
    symbolTriggered := true
    Send("{~}")
}

m:: {
    global symbolTriggered
    symbolTriggered := true
    Send("``")
}

,:: {
    global symbolTriggered
    symbolTriggered := true
    Send("*")
}

.:: {
    global symbolTriggered
    symbolTriggered := true
    Send("/")
}

/:: {
    global symbolTriggered
    symbolTriggered := true
    Send("|")
}

#HotIf  ; 结束条件热键上下文

; ===== 调试信息 =====
if (DEBUG_MODE) {
    ToolTip("keyboard_strategy.ahk loaded")
    SetTimer(() => ToolTip(), -2000)
}
