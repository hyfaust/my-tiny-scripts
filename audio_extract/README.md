# audio-extract

一个单文件的 Python + FFmpeg 命令行小工具：**查看视频文件详细信息**，以及**原位提取音轨**。

提取走的是 FFmpeg 的 **stream copy**（`-c:a copy`）——直接把原始音频比特流重新封装进一个纯音频容器，**不重新编码**。所以它无损、秒级完成，不会像转码那样损失音质或消耗 CPU。

---

## 环境要求

| 依赖 | 要求 | 说明 |
| --- | --- | --- |
| Python | 3.8+ | 只用标准库（`argparse` / `subprocess` / `json`），无需 `pip install` |
| ffmpeg | 4.0+ | 用于提取 |
| ffprobe | 4.0+ | 用于读取文件信息 |

已验证环境：`Python 3.13.5` + `ffmpeg 4.0.2` + `ffprobe 4.2.10`（Windows）。脚本避开了 FFmpeg 4.3+ 才有的参数，所以 4.0 也能跑。

确认一下它们是否在 PATH 上：

```cmd
ffmpeg -version
ffprobe -version
```

如果 FFmpeg 装在别处、或者 PATH 上有多个版本（本机就是 ffmpeg 与 ffprobe 来自不同安装包），可以用环境变量指定：

```cmd
set FFMPEG=D:\tools\ffmpeg\bin\ffmpeg.exe
set FFPROBE=D:\tools\ffmpeg\bin\ffprobe.exe
```

---

## 快速开始

```cmd
:: 1. 看视频里有什么
python audio_extract.py info movie.mp4

:: 2. 把音轨提取到视频旁边
python audio_extract.py extract movie.mp4
```

第二条命令会在 `movie.mp4` 的**同一个目录**下生成 `movie.m4a`（aac 音轨 → m4a 容器），内容与原音轨逐比特一致。

---

## 命令一：`info` — 查看详细信息

读取容器格式、时长、总码率，并逐个流列出编码、分辨率 / 声道、帧率、码率、语言等。

```console
> python audio_extract.py info movie.mp4
File       : movie.mp4
Size       : 1.24 GiB
Container  : QuickTime / MOV
Duration   : 00:03:24.512
Bitrate    : 52.10 Mb/s
Streams    : 3  (video 1, audio 2, subtitle 0)

  stream #0   video  h264 (High)  1920x1080  29.97 fps  yuv420p  50.20 Mb/s
  stream #1   audio  aac (LC)  2ch (stereo)  48000 Hz  192 kb/s  [default]  lang=eng  title=Main  audio track 0
  stream #2   audio  ac3  6ch (5.1)  48000 Hz  448 kb/s  lang=chi  audio track 1

Audio tracks available: 2
Extract with: python audio_extract.py extract movie.mp4
```

几点约定：

- `stream #N` 是 FFmpeg 的**全局流序号**（`ffprobe` 的 `index`）。
- 行尾的 `audio track N` 才是 `--track` 参数要用的**音轨序号**（0 起）。

### 用法

```cmd
python audio_extract.py info <文件或目录>... [-r] [--json]
```

| 参数 | 说明 |
| --- | --- |
| `PATH...` | 一个或多个视频文件，或目录 |
| `-r`, `--recursive` | 目录输入时递归扫描子目录（默认只看当前层） |
| `--json` | 直接打印 ffprobe 的原始 JSON（便于脚本化处理） |

---

## 命令二：`extract` — 原位提取音轨

```cmd
python audio_extract.py extract <文件或目录>... [-t SPEC] [-o DIR] [-y] [-q] [-v]
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `PATH...` | — | 一个或多个视频文件，或目录 |
| `-r`, `--recursive` | 关 | 目录输入时递归扫描子目录 |
| `-t`, `--track SPEC` | `0` | 要提取的音轨：单个数 / 逗号列表 / `all` |
| `-o`, `--output DIR` | 与源文件同目录 | 改变输出目录（不存在会自动创建） |
| `-y`, `--overwrite` | 关 | 覆盖已存在的输出；**默认跳过**，不会误删已有文件 |
| `-q`, `--quiet` | 关 | 不画进度条 |
| `-v`, `--verbose` | 关 | 打印实际执行的 ffmpeg 命令 |

### 输出命名

- 默认：`<源文件同目录>/<源文件主名><扩展名>`，例如 `D:\videos\movie.mp4` → `D:\videos\movie.m4a`。
- 加了 `-o D:\audio`：输出到 `D:\audio\movie.m4a`。
- 一个文件里有多条音轨（或用 `--track all`）时，主名后面加后缀：优先用音轨的语言标签，否则用序号。
  例如 `concert.mkv` 的两条音轨 → `concert.eng.m4a`、`concert.chi.m4a`；没有语言标签则是 `concert.track0.m4a`、`concert.track1.m4a`。

### 容器如何选择

因为不转码，容器必须装得下原本的音频编码。工具按 `codec_name` 自动选扩展名：

| 源音频编码 | 输出扩展名 | 容器 |
| --- | --- | --- |
| `aac`, `alac` | `.m4a` | MP4 / MOV 音频 |
| `mp3` | `.mp3` | MP3 |
| `mp2` | `.mp2` | MPEG audio |
| `ac3` / `eac3` | `.ac3` / `.eac3` | AC-3 / E-AC-3 |
| `dts` | `.dts` | DTS |
| `flac` | `.flac` | FLAC |
| `opus` | `.opus` | Ogg |
| `vorbis` | `.ogg` | Ogg |
| `wmav1`, `wmav2` | `.wma` | ASF |
| `pcm_*`, `adpcm_*` | `.wav` | WAV |
| 其它 / 未知 | `.mka` | Matroska Audio（几乎兼容所有编码） |

`.mka` 兜底是故意的：遇到少见的编码（如 `truehd`、`cook`）时，Matroska 几乎都能收，避免因容器不匹配而失败。

---

## 常用示例

```cmd
:: 提取第 1 条音轨（默认），输出到视频旁边
python audio_extract.py extract movie.mp4

:: 取第 2 条音轨（--track 从 0 开始）
python audio_extract.py extract movie.mp4 --track 1

:: 一次取多条，分别成文件
python audio_extract.py extract movie.mp4 --track 0,2

:: 一个文件里的所有音轨全部导出（自动加语言/序号后缀）
python audio_extract.py extract concert.mkv --track all

:: 批量处理整个目录（含子目录），输出集中到一个文件夹
python audio_extract.py extract D:\videos -r -o D:\audio

:: 覆盖已存在的输出，并显示实际命令
python audio_extract.py extract movie.mp4 -y -v

:: 安静模式，适合放进脚本
python audio_extract.py extract D:\videos -q
```

---

## 进度与批量汇总

提取时会在终端里画一行实时进度：

```
[2/5] movie.mp4 -> movie.m4a  [################------------]  62.3%   1.83x  ETA 00:03
```

百分比来自 ffprobe 读到的时长与 ffmpeg `-progress` 汇报的位置。输出被重定向到文件（非终端）时，进度条会自动降级为纯文本，不会塞满日志。

批处理结束后会打印汇总：

```
Summary: 3 succeeded, 1 skipped, 1 failed
  skipped  D:\audio\old.m4a: already exists (use -y to overwrite)
  failed   broken.mp4: no audio track
```

> **提示**：stream copy 通常不到 1 秒就完成了，进度条一闪而过是正常的。它主要是给超大文件、网络盘或慢速磁盘准备的。

---

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部成功 |
| `1` | 有文件失败或被跳过：无音轨、`--track` 越界或写法错误、ffmpeg 报错、输出已存在但没加 `-y` |
| `2` | 参数或环境错误：找不到 ffmpeg/ffprobe、输入路径不存在、没给子命令 |
| `130` | 被 `Ctrl+C` 中断 |

> 为什么 `--track` 越界算 `1` 而不是 `2`？因为音轨数量是**每个文件各不相同的**，只有读到文件之后才知道是否越界，所以它属于"这个文件处理失败"，而不是命令行本身写错了。

---

## 常见问题

**找不到 ffmpeg / ffprobe**
脚本会报 `could not find 'ffmpeg' on PATH`。把 FFmpeg 的 `bin` 目录加进 PATH，或设置 `FFMPEG` / `FFPROBE` 环境变量指向可执行文件。

**报 `no audio track`**
这个视频本身没有音频流（比如纯屏录制、静音素材）。先用 `info` 确认一下。

**报 `--track N is out of range`**
音轨序号从 0 开始。用 `info` 看 `audio track N` 那几行，那里列出的就是合法序号。

**报 `already exists` 或被跳过**
默认不覆盖任何已有文件。确认要覆盖就加 `-y`。

**aac 音轨从 ts/mkv 里拷进 m4a 会不会有问题？**
FFmpeg 会自动插入 `aac_adtstoasc` 比特流滤镜处理 ADTS 头，无需手动干预。

**提取出来的音频和原视频时长略有差异？**
容器首尾时间戳（`start_time` / priming samples）的舍入差异，属于正常现象。音频数据本身是逐比特相同的。

**能不能顺便转成 MP3？**
这个工具刻意只做无损 stream copy。要转码就直接用 FFmpeg：

```cmd
ffmpeg -i movie.mp4 -vn -c:a libmp3lame -q:a 0 movie.mp3
```
