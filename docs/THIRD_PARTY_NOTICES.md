# 第三方来源与许可

## 离线德语语音

本地合成使用 D 盘安装的 eSpeak NG 德语声音 `de`，由 `espeakng-loader==0.2.4` Windows x64 分发包提供。引擎及语言数据使用 GPL-3.0-or-later；安装时应保留上游 COPYING 和来源声明。合成发音标明为合成声音，不替代词典真人录音。

- eSpeak NG 源码：https://github.com/espeak-ng/espeak-ng
- 许可文本：https://github.com/espeak-ng/espeak-ng/blob/master/COPYING
- Windows 构建源码：https://github.com/thewh1teagle/espeakng-loader
- 分发包：https://pypi.org/project/espeakng-loader/0.2.4/


## 德语离线词典

`_internal/app_resources/dictionary/de-zh.db` 是对 Kaikki/Wiktextract 提取数据所建的 SQLite 查询索引；保留了对应词条的来源 URL。中文释义源于中文 Wiktionary 的德语词条及其贡献者，索引中的内容没有改成项目代码的许可。

数据包来源：

- https://kaikki.org/zhwiktionary/%E5%BE%B7%E8%AF%AD/index.html
- https://kaikki.org/zhwiktionary/%E5%BE%B7%E8%AA%9E/index.html

数据提取日期：2026-10-24；原始 zhwiktionary dump：2026-10-01。

原始 JSONL 的 SHA-256：

- 德语：`0776944e7e8ab24efdebbdb9810f29ed51161cf6d4f2bbe6244d9ead05ca37a9`
- 德語：`ce941c9dde8fb2004c9b44e8b7328b6ea382bdb7f71623409dadf6f68a41c4e2`

构建时合并两包，提取德语词形、中文义项、冠词、词性、IPA 和来源到本地索引。没有将缺失读音、词性或翻译作为模型推测补入。可用本项目 `prepare_offline.py` 和 `offline_dictionary.py` 从原 JSONL 重建。

Wiktionary 文字通常以 CC BY-SA 4.0 / GFDL 提供，具体页面可能有导入声明或例外。请保留词条链接、贡献者署名途径和实际适用许可，按相同方式共享要求处理再分发。

- Wikimedia 使用条款：https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use
- CC BY-SA 4.0：https://creativecommons.org/licenses/by-sa/4.0/
- GFDL：https://www.gnu.org/licenses/fdl-1.3.html
- 中文 Wiktionary 许可说明：https://zh.wiktionary.org/wiki/Wiktionary:CC_BY-SA_4.0協議文本

## 本地录音

录音来自 Wikimedia Commons。每个文件的作者、来源、许可信息保存在个人词库记录中，词条页面会显示，并随 Obsidian 笔记导出。默认源码仓库和通用桌面构建不携带用户录音；各录音使用各自的许可，并非整包统一许可。

Commons 许可说明：https://commons.wikimedia.org/wiki/Commons:Licensing/zh

## 应用组件

应用包含 CPython、Streamlit、pywebview、pythonnet 及其依赖。相关许可证保留在 `_internal` 内的软件包数据和发行元数据中，组件分别遵循自己的许可。

- CPython：https://docs.python.org/3/license.html
- Streamlit（Apache-2.0）：https://github.com/streamlit/streamlit
- pywebview（BSD-3-Clause）：https://github.com/r0x0r/pywebview
- pythonnet（MIT）：https://github.com/pythonnet/pythonnet
- PyInstaller：https://pyinstaller.org/en/stable/license.html

Microsoft Edge WebView2 使用本机已安装的 Microsoft 运行时，适用 Microsoft 的对应条款。
