# Keyboard Strategy — 键位改造方案

基于 AutoHotkey v2 的键位改造方案，针对程序员和中文打字场景优化。

## 方案概述

| 功能 | 物理按键 | 映射结果 | 触发方式 |
|------|---------|---------|----------|
| 大小写锁定 | Esc | CapsLock | 直接按 Esc |
| Esc | CapsLock | Esc | 快速按下松开（Tap） |
| Ctrl | CapsLock | Ctrl | 按住不放（Hold） |
| 符号层 | 空格 | 激活符号层 | 按住空格 + 按字母键 |
| 空格 | 空格 | 空格 | 快速按下松开（Tap） |

---

## 键位映射详解

### 1. CapsLock 双功能

CapsLock 键改为双功能键，根据按压时长输出不同按键：

```
快速按下松开（< 200ms）  →  Esc
按住不放（≥ 200ms）      →  Ctrl（可配合其他键，如 Ctrl+C、Ctrl+V）
```

**典型使用场景**：

| 操作 | 说明 |
|------|------|
| CapsLock（快速松开） | Vim 中退出插入模式、关闭对话框 |
| CapsLock + C | 复制 |
| CapsLock + V | 粘贴 |
| CapsLock + S | 保存 |
| CapsLock + Z | 撤销 |
| CapsLock + A | 全选 |

### 2. Esc 键映射

原始 Esc 键位置改为 CapsLock（大小写锁定），使用 `$` 前缀避免与 CapsLock Tap 发送的 `{Esc}` 形成循环。

```
按 Esc  →  触发 CapsLock（大小写锁定）
```

### 3. 符号层（Vim 风格布局）

按住空格键超过 200ms 后激活符号层，此时按下字母键/符号键将输出对应符号。松开空格后退出符号层。

**快速按空格** → 正常输入空格

#### 符号层映射表

##### Home Row（主键区）

| 按键 | 输出 | 说明 |
|------|------|------|
| A | `@` | 邮箱、装饰器、@mention |
| S | `#` | 注释、预处理、shell 变量 |
| D | `_` | 下划线（snake_case、常量） |
| F | `-` | 减号、连字符 |
| G | `=` | 赋值、比较 |
| H | `{` | 左花括号 |
| J | `}` | 右花括号 |
| K | `[` | 左方括号 |
| L | `]` | 右方括号 |
| ; | `:` | 冒号（Vim 命令、条件、对象） |

##### Top Row（上排 — 数字层）

| 按键 | 输出 |
|------|------|
| Q | `1` |
| W | `2` |
| E | `3` |
| R | `4` |
| T | `5` |
| Y | `6` |
| U | `7` |
| I | `8` |
| O | `9` |
| P | `0` |

##### Bottom Row（下排）

| 按键 | 输出 | 说明 |
|------|------|------|
| Z | `!` | 取反、不等于 |
| X | `%` | 取模、格式化 |
| C | `(` | 左圆括号 |
| V | `)` | 右圆括号 |
| B | `\` | 转义、路径分隔 |
| N | `~` | home 目录、按位取反 |
| M | `` ` `` | 模板字符串、命令替换 |
| , | `*` | 乘法、指针、glob 通配 |
| . | `/` | 除法、路径、注释 |
| / | `|` | 管道、逻辑或 |

---

## 工作原理

### Tap-Hold 机制

CapsLock 和空格键都采用 Tap-Hold 机制：

```
按键按下 ──→ 等待 tap_term（200ms）──→ 是否松开？
  │                                      │
  │                              （已松开）→ 触发 Tap
  │
  └──→ （未松开且按下其他键）──→ 触发 Hold
```

**CapsLock**：
- 按下时立即发送 `LCtrl down`
- 松开时判断：如果是 Tap（`A_PriorKey = "CapsLock"` 且持续时间 < 200ms），补发 `Esc`
- 否则发送 `LCtrl up`

**空格键**：
- 按下时启动延迟定时器（200ms）
- 定时器触发后激活符号层
- 松开时判断：如果符号层未激活且未触发符号，发送 `Space`

### 符号层状态管理

```
全局变量：
  spaceHeld        — 空格是否正在按住
  symbolLayerActive — 符号层是否激活
  symbolTriggered  — 本次 Hold 是否触发了符号
```

使用 AHK 的 `#HotIf` 指令实现条件热键，仅在 `symbolLayerActive = true` 时生效。

---

## 配置说明

编辑 `keyboard_strategy.ahk` 顶部的配置参数：

```ahk
global TAP_TERM := 200          ; Tap/Hold 分界时间（ms）
global DEBUG_MODE := false      ; 调试模式，显示 ToolTip
```

### TAP_TERM 调整建议

| 现象 | 调整 |
|------|------|
| 经常误触发 Esc（本想按 Ctrl） | 增大值（如 250ms） |
| Tap 有延迟感 | 减小值（如 150ms） |
| 刚开始使用 | 建议 250ms（宽松） |
| 熟练后 | 可降至 150ms（紧凑） |

### DEBUG_MODE

设为 `true` 后，按键操作会显示 ToolTip 调试信息，包括：
- CapsLock 松开时的 `A_PriorKey` 和持续时间
- 符号层激活事件

---

## 使用指南

### 安装

1. 下载安装 [AutoHotkey v2](https://www.autohotkey.com/)
2. 双击 `keyboard_strategy.ahk` 运行
3. 系统托盘出现 AHK 图标表示脚本已加载

### 开机自启

将 `keyboard_strategy.ahk` 的快捷方式放入启动文件夹：

```
Win + R → shell:startup → 回车
将快捷方式拖入打开的文件夹
```

### 退出脚本

右键系统托盘 AHK 图标 → Exit

---

## 适应建议

| 阶段 | 时间 | 建议 |
|------|------|------|
| 磨合期 | 第 1-3 天 | 将 TAP_TERM 设为 250ms，允许误触 |
| 适应期 | 第 4-7 天 | 降至 200ms，开始形成肌肉记忆 |
| 稳定期 | 第 2 周起 | 可尝试 150ms 获得更快响应 |

**练习方法**：
1. 先单独练习 CapsLock Tap/Hold（在记事本中反复测试）
2. 再练习符号层（按住空格，依次按下 home row 键输出 `@#_-= {}[]:`）
3. 最后在实际编程中使用

---

## 常见问题

### Q: 如何恢复原始 CapsLock 功能？

临时禁用：右键托盘图标 → Suspend Hotkeys

永久禁用：退出脚本或删除脚本文件

### Q: 符号层中如何输入空格？

快速按空格（Tap）即可输入空格。只有按住超过 200ms 才会激活符号层。

### Q: 在游戏中 CapsLock 行为异常？

部分全屏游戏可能不兼容 AHK。临时方案：退出脚本，或在脚本中添加游戏进程排除：

```ahk
#HotIf !WinActive("ahk_exe game.exe")
```

### Q: 与输入法切换冲突？

部分输入法使用 Shift 或 Ctrl+Space 切换，本方案不修改这些按键，理论上无冲突。如遇到问题，可将输入法切换键改为其他按键。

---

## 文件结构

```
keyboard_strategy/
├── keyboard_strategy.ahk    # AHK v2 脚本（双击运行）
└── README.md                # 本文档
```
