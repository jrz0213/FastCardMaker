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

打开选项时检查本机与媒体配置的差异，并由用户选择覆盖或同步。词典路径仅保存在本机；API Key 默认包含在配置备份中，可在通用设置关闭。Python 词典脚本单独同步到 `_fastcm_scripts.zip`，差异可逐文件选择本机或备份版本。Settings differences are resolved explicitly; dictionary paths stay local. API keys are included in settings backup by default (optional). Python parsers sync separately in `_fastcm_scripts.zip` with per-file version choices.

## 安装 / Install

- AnkiWeb: [FastCard Maker](https://ankiweb.net/shared/info/962326418), code **962326418**.
- From source: copy the contents of `src` into a folder under Anki's add-ons directory, then restart Anki. Do not copy personal configuration or credentials when sharing an installation.

## Credits

[FastWordQuery](https://github.com/sth2018/FastWordQuery), [WordQuery](https://github.com/finalion/WordQuery), [mdict-query](https://github.com/mmjang/mdict-query), [pystardict](https://github.com/lig/pystardict), [AnkiHub](https://github.com/dayjaby/AnkiHub), [snowball_py](https://github.com/shibukawa/snowball_py).

See [LICENSE](LICENSE).
