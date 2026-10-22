# GUI 与词典服务的模块结构

本次拆分按职责划分文件，保留原来的对话框类、服务类和调用方式。

AI 界面集中在 `gui/ai_ui/`：`settings.py` 管配置切换和保存，`layout.py`
管页面构建，`mapping.py` 管提示词编辑，`progress.py` 管独立进度窗口。
`query/ai_runner.py` 管 AI 后台队列，默认每分钟平滑发送 29 次。
`query/session.py` 统一浏览器与全局运行，让词典与 AI 同时执行；
`gui/query_progress.py` 提供两条独立进度及取消操作。词典返回结果与 AI 结果
均在主线程应用和保存。
连接配置、参数能力、持久化、模型目录、并发与校验集中在 `service/ai_support/`；
`diagnostics.py` 负责不包含密钥或正文的请求日志和 token 统计。
`limits.py` 管平滑发送和内部并发上限，`retry.py` 管有限 HTTP 重试。
原 `gui/ai_*.py`、`service/ai_*.py` 保留薄兼容入口，指向同一实现对象，
避免外部脚本和已有导入失效。中英文文案集中在 `translations.py`。
可同步设置写入媒体文件夹的 `_fastcmcfg.json`，本机工作副本写入用户目录的
`_fastcm_local.json`。字段映射和脚本勾选状态属于普通媒体配置；词典路径及调度进度仅存本机。
AI 连接和当前 Python 脚本共同备份至媒体库 `_fastcm_backup.zip`，AI 元数据的本机缓存为
`fastcm/ai/settings.json`，运行时读取普通配置文件和本机 `.py` 脚本，ZIP 仅作备份。API Key 仅存 Windows 凭据管理器或 macOS
钥匙串，由 `utils/system_password.py` 访问，不进入配置或 ZIP。`service/ai_support/migration.py`
检测已知旧配置及备份中的明文 Key，写入系统凭证并读回验证后才清除明文；失败时保留原文件。
`gui/config_sync.py` 在打开选项前提供本机覆盖媒体、媒体同步到本机及取消三种选择。
请求适配位于 `service/ai.py`，
`service/ai_support/conversation.py` 分别组装 Chat Completions、Responses 和 Messages 的无状态历史；
自定义连接的 `interface_format` 随配置保存，非标准路径按此格式发送，标准后缀冲突时拒绝保存。
词典脚本窗口的用户／AI 消息进入历史，本地处理和调试记录放入当前请求的 `local_information`；
其中仅附带最新 AI 回复起产生的本地信息，避免每轮重发旧调试资料。
相同脚本通过内容指纹和来源引用避免在历史与附件之间重复发送。普通笔记 AI 查询不携带这些上下文。
`service/script_reply.py` 解析 `ai-message` 与完整 `rules`／`code`，纯消息不修改脚本；
`gui/script_message_view.py` 仅负责安全 Markdown 和 JSON 展示，原始回复用于复制及历史。
`utils/script_editor.py` 显式调用文本编辑器，避免通过 `.py` 文件关联执行脚本。
基础 Markdown 转换位于 `utils/markdown.py`。使用方法见 [AI 字段填充](usage.zh-CN.md)。
操作流程见 [图文指南](usage.zh-CN.md)。

## GUI

| 文件 | 职责 |
| --- | --- |
| `src/gui/options.py` | 配置窗口生命周期、保存、切换配置和事件响应 |
| `src/gui/options_layout.py` | 配置窗口工具栏、标签页容器和底部按钮的布局 |
| `src/gui/options_tab.py` | 字段映射页的生命周期、选择状态和配置数据读取 |
| `src/gui/mapping_controls.py` | 字段映射行的控件、信号绑定、词典和数据项选项 |
| `src/gui/options_widgets.py` | 忽略滚轮的下拉框、可编辑名称的标签栏 |
| `src/gui/options_controller.py` | 配置和批量查词的业务逻辑，沿用现有控制器 |
| `src/gui/foldermanager.py`、`dictmanager.py` | 目录和词典管理的操作、保存和退出流程 |
| `src/gui/folder_layout.py`、`dict_layout.py` | 对应管理窗口的界面构建 |

布局函数接收对话框对象，保留原来的控件属性和信号接收方法；
字段映射控件函数通过 `TabContent` 的原有方法调用，保留方法覆盖能力。
`TabContent`、`CTabBar` 和 `NoScrollComboBox` 仍可从 `gui.options` 导入。

## Service

| 文件 | 职责 |
| --- | --- |
| `src/service/base.py` | 保留旧导入入口，重新导出服务类和公共辅助函数 |
| `src/service/core.py` | 通用服务接口、字段分发、查询缓存 |
| `src/service/result.py` | `QueryResult` 返回值及样式元数据 |
| `src/service/helpers.py` | 注册和导出装饰器、HTML 解析、样式和资源命名 |
| `src/service/web.py` | 网络词典的请求、流读取和下载 |
| `src/service/local.py` | 本地词典状态、共享建库缓存、后台队列和 Qt 信号 |
| `src/service/mdx.py` | MDX 查询、重定向和释义缓存 |
| `src/service/mdx_media.py` | MDX 媒体提取、模糊匹配和 Anki HTML 适配 |
| `src/service/stardict.py` | StarDict 建库调用和查询结果转换 |
| `src/service/custom_scripts.py` | 外部词典脚本的路径适配、复制和配置启用 |

词典脚本可以继续使用 `from ..base import *` 或原来的显式导入。
兼容入口导出的是同一组类和装饰器，因此继承判断、导出字段排序和
`LocalService` 的共享建库状态仍使用同一份对象。

`MdxService` 继承 `MdxMediaMixin`，自定义词典仍可覆盖
`adapt_to_anki()`、`save_default_file()` 等方法。静态资源的默认目录
仍是 `src/service/static`。

## 验证

在项目根目录运行：

```sh
python -m unittest discover -s tests -v
```

测试使用真实的拆分模块，以替身代替 Anki、Qt 和网络边界，覆盖导入兼容性、
字段导出顺序、共享建库状态与信号、网络请求、MDX/StarDict 查询、
媒体提取、脚本适配和映射下拉框选项。

基础检查不依赖 Anki。安装 `PyQt6`、`requests` 和 `beautifulsoup4` 后，
同一命令还会运行真实控件及文件处理检查；没有这些依赖时会跳过相应测试。
Qt 检查采用 `offscreen` 模式，不显示窗口，也不打开用户的 Anki 收藏。
覆盖窗口构建、保存、标签页增删和改名、词典状态刷新、来源字段切换、
目录及词典管理，以及实际 StarDict 文件读取、HTML/CSS 和媒体处理。
同时检查所有随项目提供的词典脚本能否导入。

在这轮检查中修复了两处重构前已存在的问题：

- 状态刷新会触发下拉框变更信号，重置已选的数据项并误标记为未保存。
  刷新时现在会阻止这些信号，并保留当前字段映射。
- 模糊匹配音频后，HTML 替换遗漏了链接的起始标签。
  现在替换完整的音频链接，保留周围的 HTML。

这些检查不代表完整的 Anki 环境验证。真实收藏中的批量更新、外部网络词典
的可用性和实际 MDX/MDD 文件仍需在对应环境中验证。


## 可移植脚本与备份

`service/dictionary_binding.py` 以 MDX 文件名优先关联本机目录，内部标题可选，兼容旧路径。`service/script_library.py` 管理本机运行副本，`service/script_backup.py` 按排序后的文件清单比较内容指纹。`utils/backup_store.py` 原子更新包含 AI 配置和 Python 脚本的备份 ZIP，字段配置与基本偏好继续写媒体 JSON；`gui/backup_controls.py` 提供自动／手动备份与 ZIP 导入导出。`gui/script_compare.py` 提供互斥版本选择和只读查看。目录扫描不再同步相邻 Python 文件，也不因移除目录而删除脚本。AI 对话不自动落盘。

`service/python_scripts.py` 定义直接返回 Python 的提示词，静态检查语法和注册类。JSON 模式仍通过可信模板生成脚本；Python 模式不自动执行，手动调试才执行完整代码，属于普通 Python 执行而非沙箱。
