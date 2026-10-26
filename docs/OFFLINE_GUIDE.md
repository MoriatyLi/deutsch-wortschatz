# 本地离线使用

离线查询通过独立 SQLite 索引完成。索引与个人词库分开，更新词典不会删除个人词条。

## 准备词典

从 [Kaikki “德语”](https://kaikki.org/zhwiktionary/%E5%BE%B7%E8%AF%AD/index.html) 和 [“德語”](https://kaikki.org/zhwiktionary/%E5%BE%B7%E8%AA%9E/index.html) 页面下载对应中文 Wiktionary 德语 JSONL。两种标题的数据包可以合并导入。

```powershell
.\.venv\Scripts\python.exe .\prepare_offline.py --source .\data\dictionaries\zh-de.jsonl .\data\dictionaries\zh-de-traditional.jsonl
```

默认输出 `data/dictionaries/de-zh.db`，并在源码版词库设置中关闭在线查询与 Edge TTS。也可在侧栏指定本地 JSONL 导入。导入采用临时文件和原子替换，失败不会替换旧索引。

成功建索引后可删除原始 JSONL、下载片段和进度日志，保留来源及校验信息。再次重建需要重新获取源文件。仓库不携带词典大文件。

用于最初构建的数据版本为 2026-10-24 提取、2026-10-01 zhwiktionary dump，索引有 168,289 个词形和 267,409 个义项；以后版本的覆盖范围可能不同。

## 日常查词

侧栏显示“完全离线”时，查词、搜索、校对、CSV 和 Obsidian 导出在本机完成，不向词典或翻译服务发送输入词语。

小写词与首字母大写词可能有不同候选。多义项、多种 IPA 或缺失冠词时，请核对原文；词典没有的词仍可保存并手动补充。中文可能简繁混排，候选保持待复核。人工修改字段在重新查询时保留。

## 录音与备份

已有本地录音可离线播放；词典含 IPA 并不代表已经有录音。离线模式不会调用在线 TTS。可以在 D 盘配置 eSpeak NG 德语资源后生成本地合成音频；已有真人录音保留，新生成声音明确标为合成。安装步骤见 README。

源码版个人数据在 `data/`，桌面版在 `%LOCALAPPDATA%\DeutschWortschatz`。停止应用后备份个人数据目录。词典索引可单独备份，或从原始 JSONL 重建。

词典与录音的来源及许可见 [第三方说明](THIRD_PARTY_NOTICES.md)。
