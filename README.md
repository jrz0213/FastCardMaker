# FastCard Maker

Fill Anki note fields with AI or local and online dictionaries. Menu name: **FastCM**.

本插件基于 [FastWordQuery (FastWQ)](https://github.com/sth2018/FastWordQuery) 和 [WordQuery](https://github.com/finalion/WordQuery) 开发，保留原作者署名与 GPL 许可证。

This add-on builds on FastWordQuery and WordQuery. Original author credits and the GPL license are retained.

## 操作指南 / User guides

- [中文图文指南](docs/usage.zh-CN.md)
- [English illustrated guide](docs/usage.en.md)

## 使用 / Get started

1. 安装插件并重启 Anki，从 **FastCM → 选项** 打开配置。
2. 配置 AI 连接或启用词典，选择笔记类型，为目标字段选择来源并填写提示词或数据项，点击 **确定**。
3. 在浏览器选择少量笔记，使用 **FastCM → 查询选中项** 试查；确认后使用 **全类型查询** 批量处理。

1. Install the add-on and restart Anki. Open **FastCM → Options**.
2. Connect AI or enable dictionaries. Select a note type, map target fields to sources and prompts/data items, then save with **OK**.
3. Test a few notes with **FastCM → Query selected** in the Browser. Use **Query whole note types** for larger batches.

AI can work with concepts, questions, study material and vocabulary. Prompts can reference several fields, for example `Using {{Topic}}, answer {{Question}}`. The add-on fills existing notes; card templates determine how fields appear.

AI 可用于概念、问题、学习材料及词汇。提示词支持多个字段，例如 `结合{{主题}}回答{{问题}}`。插件填充已有笔记，卡片显示方式由 Anki 模板决定。

通用设置可选择自动或手动备份。AI 配置和 Python 脚本平时从本机文件读取，备份时统一打包到 `_fastcm_backup.zip`；字段配置和勾选状态保存在媒体配置文件，词典路径仅存本机。脚本差异可逐文件选择本机或备份版本。AI 解析支持 JSON 规则或直接生成 Python，点击问号查看说明。

API Key 保存在本地，由系统统一管理，不会随配置上传或同步。

General settings offer automatic or manual backup. AI settings and Python parsers are read from local files during normal use and packaged together in `_fastcm_backup.zip` for backup. Field mappings and enable flags stay in the media configuration, while dictionary paths stay local. Script conflicts offer per-file version choices. AI parsing supports JSON rules or direct Python output; click **?** for help.

API keys are stored locally and managed by the operating system. They are not uploaded or synced with your configuration.

## 安装 / Install

- AnkiWeb: [FastCard Maker](https://ankiweb.net/shared/info/962326418), code **962326418**.
- From source: copy the contents of `src` into a folder under Anki's add-ons directory, then restart Anki. Do not copy personal configuration or credentials when sharing an installation.

## Credits

[FastWordQuery](https://github.com/sth2018/FastWordQuery), [WordQuery](https://github.com/finalion/WordQuery), [mdict-query](https://github.com/mmjang/mdict-query), [pystardict](https://github.com/lig/pystardict), [AnkiHub](https://github.com/dayjaby/AnkiHub), [snowball_py](https://github.com/shibukawa/snowball_py).

See [LICENSE](LICENSE).
