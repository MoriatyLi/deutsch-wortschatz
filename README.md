# Deutsch Wortschatz · 本地德语词库

在本机保存德语单词、中文释义、冠词、词性、IPA、发音和校对记录，支持离线词典查询、Windows 桌面应用和 Obsidian 单向导出。

仓库包含源码、测试和构建工具。个人词库、录音、离线词典大文件、虚拟环境和应用包均保留在本机，不纳入版本管理。

## 功能

- 按词形查词并保留义项候选、出处和读音差异；缺失字段留空，不推测补全。
- 中文释义、语法、IPA 和备注可编辑；重新查询时保留人工修改。
- SQLite 离线索引，配置后可关闭全部在线词典和 TTS 请求。
- 播放已保存的本地录音，导出 CSV。
- 将整个词库保存到一份 Obsidian Markdown 单词表，可指定路径并自动更新；保留管理区域之外的手写内容。
- 可选导出逐词笔记及本地音频，保留来源和许可。
- 可构建自带 Python 运行时的 Windows x64 桌面应用。

## 源码运行

需要 Python 3.10+ 和 Windows PowerShell。安装依赖：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

双击 `start.bat`，或运行：

```powershell
.\start.ps1
```

打开 `http://127.0.0.1:8501/`。程序仅监听本机；终端保持运行，按 Ctrl+C 停止。可以使用 `-Port 8502` 更换端口，或用 `-NoBrowser` 禁止自动打开浏览器。

`ExecutionPolicy Bypass` 仅影响此次进程，不修改系统的永久执行策略。安装脚本优先使用项目虚拟环境；若 Python 缺少 ensurepip，可通过基础 Python 的 pip 安装到 `.venv`。

## 配置离线词典

从 [Kaikki 简体标题“德语”](https://kaikki.org/zhwiktionary/%E5%BE%B7%E8%AF%AD/index.html) 和 [繁体标题“德語”](https://kaikki.org/zhwiktionary/%E5%BE%B7%E8%AA%9E/index.html) 页面下载对应 JSONL。保存为 `data/dictionaries/zh-de.jsonl`、`zh-de-traditional.jsonl` 后建立索引：

```powershell
.\.venv\Scripts\python.exe .\prepare_offline.py --source .\data\dictionaries\zh-de.jsonl .\data\dictionaries\zh-de-traditional.jsonl
```

导入成功后自动关闭在线查询和 Edge TTS；也可以在侧栏导入本地 JSONL。日常查词使用 `data/dictionaries/de-zh.db`，无需保留原始 JSONL，但重建索引时需重新下载。各数据包覆盖范围和格式以实际下载版本为准。

离线查词不会为新词自动下载录音。多个读音、缺失 IPA、没有中文释义等情况会明确保留，需结合原文校对。见 [离线说明](docs/OFFLINE_GUIDE.md)。

## 本地德语语音（资源安装在 D 盘）

没有真人录音时，可使用 eSpeak NG 的德语声音 `de` 在本机合成 WAV。合成不需要联网，已有真人录音优先保留。规则合成的声音较机械，重音和同形异音仍需核对。

将语言资源安装到一个有写权限的 D 盘目录，例如：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps --target "D:\BaiduNetdiskDownload\DeutschWortschatz\Speech" --cache-dir "D:\BaiduNetdiskDownload\DeutschWortschatz\pip-cache" espeakng-loader==0.2.4
```

在侧栏填写“本地德语语音目录（D盘）”并启用自动生成。新增词条会自动补音，已有词可点击“补全缺失的离线读音”。生成的 WAV 保存在个人词库的 `audio/`，可以随 Obsidian 单词表导出。语音引擎及语言数据留在 D 盘，不打入 C 盘的应用依赖目录。

## 录入时选择相近词

输入后按 Enter 或点击输入框外部，会显示本地候选词。支持前缀、不区分大小写、常见拼写偏差，以及 `ae/oe/ue/ss` 的德语替代写法。候选旁显示词形、冠词与中文释义。

例如输入 `wssser`，在“你要找的是哪个词？”中选择 Wasser，再点击“加入词库”；也可以选择“按原输入加入”。候选只作提示，不会自动修改或保存输入，检索不访问外网。

## Obsidian 单词表

1. 在侧栏“Obsidian 单词表”中填写目标 `.md` 文件完整路径，必须位于已有的 Obsidian Vault 中。
2. 点击“确定位置并保存单词表”。默认路径为当前用户 `Documents\Obsidian Vault\德语单词.md`。
3. 如需自动更新，勾选“保存词条后自动更新单词表”，再点击保存按钮。

已有笔记内容会保留，程序只更新 `DEUTSCH_VOCAB_TABLE_BEGIN` 与 `DEUTSCH_VOCAB_TABLE_END` 标记之间的内容。手写笔记放在标记外。标记缺失或重复时拒绝替换，避免误写私人内容。

已有录音复制到 Vault 的 `Deutsch/Audio/`，通过本地链接播放。旧的逐词笔记导出可独立使用，在侧栏填写 Vault 文件夹后操作。

## 数据位置与备份

- 源码运行：默认 `data/vocab.db`、`data/audio/`。
- 桌面版：默认 `%LOCALAPPDATA%\DeutschWortschatz`，与应用程序文件夹分离。
- 可通过 `DEUTSCH_VOCAB_DATA_DIR` 指定数据目录。源码与桌面版共享数据时应使用同一个目录，避免把两个独立词库自动写入同一张单词表。

关闭应用后备份个人数据文件夹。离线词典索引与个人词库分别保存，更新词典不会重建个人词条。

## 构建 Windows 桌面应用

Windows 10/11 x64，建议 Python 3.13。先安装依赖并准备离线索引：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_app.ps1
```

结果为 `dist/DeutschWortschatz/DeutschWortschatz.exe` 和 `dist/DeutschWortschatz-Windows-x64.zip`。完整解压后运行，并保留 `_internal` 文件夹。目标电脑不需要安装 Python，需要 Microsoft Edge WebView2 Runtime。

默认构建使用空的个人词库，不携带个人词条、录音、Vault 路径和查询缓存。仅供自己使用且需要携带源码目录的词库时，可以显式运行 `build_app.ps1 -IncludePersonalData`；此类包不应公开上传。已有桌面用户的数据不会因更新应用被种子库覆盖。详见 [桌面版说明](docs/DESKTOP_GUIDE.md)。

## 可选在线功能

侧栏可主动启用 Wiktionary、MyMemory 翻译和 Edge TTS。在线查询会发送输入词语，服务可能超时或有配额限制。译文及读音需要人工复核。Edge TTS 另需安装：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Tts
```

TTS 是在线合成语音，不属于本地录音，也不保证与所选义项对应。桌面默认构建不内置此可选依赖。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试覆盖存储迁移、词典解析、离线查询、人工修改保护、Obsidian 安全写入和应用操作。Windows 桌面构建完成后，可以在全新临时数据目录验收冻结程序：

```powershell
.\.venv\Scripts\python.exe tools\smoke_packaged_app.py dist\DeutschWortschatz\DeutschWortschatz.exe data\release-smoke
```

该检查不打开浏览器，通过本机协议实际提交词条，验证离线查词、单词表路径、手写内容保留、重启和退出清理。

## 来源与许可

词典来自 Wiktionary / Kaikki，录音来自 Wikimedia Commons。第三方内容适用其实际来源的许可，不因导出或建立索引变为项目代码的许可。请保留词条来源、录音作者和相应许可；见 [第三方说明](docs/THIRD_PARTY_NOTICES.md)。本仓库不附带第三方词典或用户数据。
