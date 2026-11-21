# LM Studio 模型下载提速

用 hf-mirror 镜像 + aria2c 多线程，替代 LM Studio 内置下载器，把模型下载从 ~100 KB/s 提到 ~6 MB/s。

## 为什么慢

LM Studio 内置下载器只对 `huggingface.co` 开**单条连接**，在国内网络下会被重置/限速，实测：

| 路径 | 速度 |
|---|---|
| LM Studio 内置下载器 | ~100 KB/s，且频繁 `ECONNRESET` |
| 直连 huggingface.co | 连接被重置 |
| 本脚本（hf-mirror + 16 连接） | 5.7–6.3 MB/s |

单条连接被限速是主因，换镜像 + 多连接绕开它。

## 前置条件

需要以下命令可用（缺哪个都会明确报错）：

- `bash` —— Git Bash 或 MSYS2 自带
- `curl`
- `python`（或 `python3`，需带标准库 `json`）
- `aria2c` —— 没有就 `scoop install aria2`
- `sha256sum`

## 用法

```bash
# 1. 先看仓库里有哪些文件（不下载）
bash dl_hf_fast.sh HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive

# 2. 下载指定文件，默认存到 ~/.lmstudio/models/<repo_id>/
bash dl_hf_fast.sh HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive \
  Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf

# 3. 一次下多个文件（空格分隔）
bash dl_hf_fast.sh HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive \
  Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf \
  mmproj-Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-BF16.gguf

# 4. 下载到自定义目录
bash dl_hf_fast.sh <repo_id> <file> -d /d/models
```

下完直接打开 LM Studio 即可，模型会自动出现在列表里（正在运行时通常也会热扫描到）。

## 参数与环境变量

| 形式 | 含义 | 默认值 |
|---|---|---|
| `<repo_id>` | 仓库标识，形如 `owner/name` | 必填 |
| `<file...>` | 仓库内文件名，可给多个；省略则只列出文件清单 | 无 |
| `-d DIR` | 输出目录 | `~/.lmstudio/models/<repo_id>/` |
| `HF_MIRROR` | 镜像地址 | `https://hf-mirror.com` |
| `ARIA_CONN` | 每服务器并发连接数 | `16` |
| `ARIA2C` | aria2c 可执行文件路径 | 自动探测 |
| `PYTHON` | python 解释器路径 | `python` → `python3` |

例：

```bash
ARIA_CONN=24 HF_MIRROR=https://hf-mirror.com bash dl_hf_fast.sh <repo_id> <file>
```

## 关于运行环境

脚本在 Git Bash / MSYS2 下原生运行。**如果你直接敲 `bash`，而环境里的 `bash` 指向 WSL2，脚本会自动检测到并重新执行到 `C:\Program Files\Git\bin\bash.exe`**，不需要手动指定。

这样做的原因是 WSL 侧通常既没有 aria2c/python，Windows 版 `aria2c.exe` 也解析不了 `/mnt/c/...` 这种 POSIX 路径。若 Git 装在别处，改脚本里的 `GB=` 变量即可。

不要用 `sh dl_hf_fast.sh` 调用：脚本用到数组和 `[[ ]]`，dash 会报语法错。

## 行为说明

- **断点续传**：同样命令重跑即可续传（`aria2c -c`），不会重头下。
- **完整性校验**：从镜像的 tree API 取该文件的 sha256，下完自动比对；**不一致就删掉文件并报错**，不会留下坏模型。
- **稀疏文件**：使用 `--file-allocation=none`，中断后重启不会重写整个文件。
- 中途个别 `[ERROR] ... errorCode=29` 是镜像回源 xet CDN 的连接中断，aria2 会自动重连，最终哈希正确即可忽略。

## 量化怎么选

| 量化 | 体积（9B 级） | 适用 |
|---|---|---|
| `Q4_K_M` | ~5.2 GiB | 默认推荐，体积/质量平衡 |
| `Q5_K_M` / `Q6_K` | ~6–7 GiB | 质量优先，显存/内存充足 |
| `Q8_0` | ~8.9 GiB | 接近原始精度 |
| `BF16` / `F16` | ~16.7 GiB | 需要最高精度 |

带 `mmproj-` 前缀的文件是**视觉投影**，多模态模型需要它才能读图；不下载也能当纯文本模型用。

## 排错

| 现象 | 处理 |
|---|---|
| `aria2c not found` | `scoop install aria2`，或 `ARIA2C=<路径>` 指定 |
| `failed to fetch repo metadata` | 镜像不可达，换 `HF_MIRROR` 或稍后重试 |
| `sha256 mismatch` | 文件已自动删除，重跑一次即可 |
| LM Studio 列表里看不到 | 完全退出 LM Studio（托盘右键 Quit）再启动 |
| 下载还是很慢 | `ARIA_CONN=32` 增加并发；或确认没有别的下载占满带宽 |