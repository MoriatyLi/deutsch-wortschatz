# Windows 桌面版使用说明

将应用 ZIP 完整解压，双击 `DeutschWortschatz.exe`。保留同目录的 `_internal` 文件夹，不要只复制 exe 或在压缩包内直接运行。

无需安装 Python。支持 Windows 10/11 x64，桌面窗口需要 [Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。

## 离线使用

构建前配置的 SQLite 词典随应用打包。首次启动默认关闭在线查询和 Edge TTS，日常查词不需要联网。词典字段缺失时留空，不推测语法或读音；一个词有多个候选时应结合原文选义项。

默认构建的个人词库为空；只播放已有本地录音，不会在离线状态为所有新词生成声音。

## 个人数据与更新

个人词库、设置和录音位于 `%LOCALAPPDATA%\DeutschWortschatz`。词条在 `vocab.db`，录音在 `audio/`。备份前关闭应用，复制整个个人数据文件夹。

更新时解压新版本即可，原有个人词库不会被种子库覆盖。内置词典路径会随整个应用文件夹移动而调整，主动设置的其他词典路径会保留。

源码版默认使用项目的 `data/`，与桌面版独立。需要共享词库时，先将源码版的 `DEUTSCH_VOCAB_DATA_DIR` 环境变量设为上述桌面数据目录。

## Obsidian 单词表

侧栏“Obsidian 单词表”默认指向当前用户 `Documents\Obsidian Vault\德语单词.md`。可以修改为已有 Vault 中的其他 `.md` 文件，再点击“确定位置并保存单词表”。勾选自动更新后，新增、校对和删除词条会更新汇总表。

表格包括冠词、词性、中文释义、IPA、校对状态、备注、来源和已有录音链接。音频复制到 Vault 的 `Deutsch/Audio/`。

程序仅更新 `DEUTSCH_VOCAB_TABLE_BEGIN` / `DEUTSCH_VOCAB_TABLE_END` 标记之间的区域，保留其他内容。手写笔记放在标记外。单独的“逐词笔记”功能可按需配置。

## 构建方式

安装 `requirements-build.txt`，先将本地词典建立为 `data/dictionaries/de-zh.db`，然后运行 `build_app.ps1`。

默认使用空种子库，排除个人录音。`-IncludePersonalData` 仅用于显式制作个人包，使用 SQLite 一致性备份携带项目 `data/vocab.db` 的词条与录音，清理机器路径和缓存。个人包请留在本机。

## 启动日志

数据目录的 `launcher.log`、`server.log` 记录启动失败原因。程序自动选择空闲本机端口，仅监听 `127.0.0.1`，关闭主程序后服务退出。
