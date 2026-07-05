# 项目文件结构

```
有道云笔记爬取/
├── scripts/                         # 工具脚本目录
│   ├── youdao_export_cloak.py       # 有道云笔记批量导出主脚本
│   ├── fix_code_format.py           # Markdown 代码块格式修复工具
│   └── youdao_login_state.json      # 登录状态持久化（自动生成）
├── logs/                            # 运行日志
│   └── debug_export.log             # 导出调试日志
├── tests/                           # 测试代码、临时代码、临时结果
│   └── fix_code_blocks.py           # （旧版）代码块检测脚本
├── cloak_user_data/                 # 浏览器用户数据目录（自动生成）
│   └── Default/                     # Chromium 用户配置
├── backup/                          # 脚本备份
├── 有道云笔记/                        # 导出输出目录（默认，按日期分目录）
│   ├── 2026-07-05/                   # 每次导出创建日期子目录
│   │   ├── Python/                   # 按原始目录结构组织
│   │   │   ├── Python 学习(1).md
│   │   │   ├── Python 学习(1)_1.png
│   │   │   └── ...
│   │   └── AI 人工智能/
├── SKILL.md                         # Claude Code 技能定义（YAML frontmatter + 指令）
├── AGENTS.md                        # 本文件 — 项目架构与开发指南
├── requirements.txt                 # Python 依赖
├── 有道云笔记爬取.code-workspace      # VS Code 工作区配置
```

# 技术架构

## 整体架构
基于 **Playwright + CloakBrowser** 的自动化浏览器方案，通过模拟用户操作来导出有道云笔记内容。
CloakBrowser 可以模拟人类指纹，避免被检测到。

## 核心模块

### 1. 浏览器管理 (`create_browser` / `close_browser`)
- 使用 `playwright.sync_api` 驱动 Chromium 浏览器
- 通过 `launch_persistent_context` 持久化用户数据到 `cloak_user_data/` 目录，实现登录状态复用
- CloakBrowser 负责自动下载和管理浏览器二进制文件

### 2. 登录检测 (`wait_for_login`)
- 自动检测页面 URL 和侧边栏元素，判断登录状态
- 支持 5 分钟超时等待，无需手动按回车

### 3. 页面交互 (`ensure_root` / `double_click_item_by_index` / `go_to_url`)
- 通过 CSS 选择器定位侧边栏"我的文件夹"并点击进入根目录
- 通过 `dblclick` 双击文件列表项，根据双击后的页面状态（文件列表变化 / 编辑器出现）区分笔记和文件夹
- 处理 SPA 缓存问题：检测编辑器标题是否匹配，不匹配则重试

### 4. 内容提取 (`extract_note_content`)
- 从 `#bulb-editor` 或 `#cache-md-editor` iframe 中提取笔记 HTML
- 提取标题（`textarea.css-4wnwuk` 等选择器）
- 通过编辑器模板关键词过滤空笔记

### 5. HTML 转 Markdown (`html_to_markdown`)
- 使用 BeautifulSoup 解析编辑器内部 HTML
- 按 `data-block-type` 分类处理：heading、paragraph、list、todo、code-block、quote、divider、image
- 支持内联样式（bold、italic、strikethrough、underline、code）和链接转换
- 图片占位符用 `<!--IMG:{idx}-->` 标记

### 6. 图片下载 (`download_image` / `process_images`)
- 复用浏览器 cookies 通过 `requests` 库下载图片
- 支持 3 次重试
- 将 Markdown 中的图片占位符替换为本地图片引用

### 7. 递归导出 (`export_recursive`)
- 深度优先遍历笔记目录树
- 按原始目录结构在本地创建对应文件夹保存 `.md` 文件
- 导出完成后自动返回父目录继续处理

### 8. 代码块格式修复 (`scripts/fix_code_format.py`)
- 自动发现未包裹的代码段并添加 ``` 标记
- 支持 Python / JavaScript / C++ / bash 语言检测
- 修复有道云笔记导出造成的换行丢失问题
- 自动修正语言标签（如 `javascript` → `python`）

## 技术栈

- **语言**: Python 3.12+
- **浏览器自动化**: Playwright (sync API) + CloakBrowser
- **HTML 解析**: BeautifulSoup 4
- **HTTP 请求**: requests
- **用户数据持久化**: Chromium `launch_persistent_context`

# 测试目录

测试代码、临时代码及临时结果统一保存在 `tests/` 目录下。

# 导出工具用法

## youdao_export_cloak.py

有道云笔记批量导出工具（CloakBrowser 版），只导出"我的文件夹"根目录下的全部笔记（含子文件夹递归）。

### 命令行用法

```powershell
python scripts/youdao_export_cloak.py --list                          # 只列出根目录结构
python scripts/youdao_export_cloak.py                                 # 导出全部
python scripts/youdao_export_cloak.py --start 0 --count 2             # 导出根目录下前 2 个项目
python scripts/youdao_export_cloak.py --folder "Python"               # 只导出根目录下指定名称的项目
python scripts/youdao_export_cloak.py --output ./export               # 指定输出目录（默认在 有道云笔记/ 下创建日期子目录）
```

### 登录状态

用户数据目录自动保存在 `cloak_user_data/` 下，首次登录后下次自动保持登录。

### 核心流程

1. 启动 CloakBrowser 持久化上下文，复用登录状态
2. 导航到有道云笔记网页版，检测登录状态
3. 进入"我的文件夹"根目录，列出文件列表
4. 按 `--start` / `--count` / `--folder` 参数筛选待导出项
5. 递归遍历选中目录，对每个笔记执行：
   - 双击打开笔记编辑器
   - 提取 HTML 内容
   - 转换为 Markdown
   - 下载图片并替换引用
   - 调用 `fix_code_format.py` 修复代码块格式
   - 保存 `.md` 文件到对应目录
6. 导出完成后关闭浏览器

## fix_code_format.py

Markdown 代码块格式修复工具（由 `youdao_export_cloak.py` 自动调用）。

### 命令行用法

```powershell
python scripts/fix_code_format.py <markdown文件路径>
```

### 模块导入

```python
from scripts.fix_code_format import fix_markdown, fix_markdown_file
fixed = fix_markdown(original_content)       # 修复字符串
fix_markdown_file("笔记.md")                  # 修复文件
```

### 修复流程

1. **代码块发现** — 扫描未被 ``` 包裹的代码行，自动添加代码块标记并检测语言
2. **换行修复** — 通过语法特征（`):`、`class`、`def` 等）恢复丢失的换行符

# Claude Code 技能 (SKILL.md)

本项目在根目录放置了 `SKILL.md`，注册为 Claude Code 技能。

| 项目 | 说明 |
|------|------|
| 文件名 | `SKILL.md`（存放在项目根目录） |
| 触发方式 | Claude 检测到用户请求与有道云笔记导出相关时自动加载 |
| 匹配字段 | `description`（技能功能和触发条件）+ `when_to_use`（补充触发短语） |
| 内容原则 | YAML frontmatter 始终加载，正文仅在技能被激活时加载 |

技能正文使用**祈使句指令**风格，包含前置检查、导出步骤、常用选项、注意事项。Claude 被触发后应直接执行导出流程，而非展示文档。

# 爬虫开发思路

智能体按以下流程开展工作：

## 整体流程

1. **侦查阶段** — 先用 Playwright + CloakBrowser 打开目标网页，通过 `page.evaluate` 注入 JS 探查 DOM 结构、CSS 选择器、AJAX 接口、数据加载方式等。
2. **分析阶段** — 编写 `_analyze_*.py` 等临时分析脚本，针对性地验证页面元素特征（如区分文件/文件夹的 DOM 属性、图标差异、右键菜单类型等），确认交互方式和数据响应规律。
3. **实现阶段** — 基于分析结论编写正式爬虫代码，确保选择器准确、交互逻辑可靠、异常处理完备。
4. **验证阶段** — 在真实环境中运行测试，对比输出与预期结果，必要时回到第 1 或第 2 步补充分析。

核心原则：**先研究清楚再动手写代码**，避免盲目猜测 DOM 结构和接口行为。

## 研究方法工具箱

### 页面结构探查
- **DOM 树分析**: 用 `page.evaluate` 递归遍历 body 子节点，输出 tag/class/text 摘要，快速理解页面骨架。
- **CSS 选择器有效性验证**: 在浏览器控制台用 `document.querySelectorAll(...)` 实时测试选择器，确认能命中目标元素。
- **Shadow DOM 穿透**: 检查是否有 `shadowRoot`，必要时通过 `element.shadowRoot` 深入内部结构。
- **iframe 递归分析**: 遍历所有 iframe，逐一提取 `contentDocument` 内部的 DOM 结构。

### 网络流量分析
- **XHR/Fetch 拦截**: 用 `page.route` 或 `page.on('request')` 捕获所有网络请求，提取 API 端点、请求参数、响应格式。
- **WebSocket 监听**: 检查是否有实时推送通道，捕获 `ws://` 或 `wss://` 连接的消息内容。
- **响应数据分析**: 对捕获到的 JSON 响应，分析字段含义、分页方式、加密字段等。
- **请求重放验证**: 拿到 API 端点后，用 `requests` 或 `curl` 在浏览器外重放请求，验证接口是否可脱离浏览器调用。

### 交互行为分析
- **事件监听探查**: 通过 `getEventListeners(el)` 或 Chrome DevTools Protocol 查看元素绑定了哪些事件（click、dblclick、contextmenu 等）。
- **SPA 路由分析**: 监听 `hashchange` 和 `popstate` 事件，通过 `history.pushState` 代理追踪路由变化，理解页面跳转逻辑。
- **状态变化检测**: 操作前后对比 DOM 差异（新增/移除元素、属性变化、URL 变化），确定操作触发的实际效果。
- **超时与加载态**: 观察 loading 动画、骨架屏、网络请求耗时，确定合理的等待时间。

### 数据模型分析
- **`data-*` 属性挖掘**: 遍历元素上的所有 `data-*` 属性，尤其是 `data-id`、`data-type`、`data-entry-type` 等业务标识字段。
- **全局变量探查**: 在控制台遍历 `window` 对象，查找 `__INITIAL_STATE__`、`__DATA__`、`APP_CONFIG` 等预注入数据。
- **localStorage / sessionStorage / IndexedDB**: 检查客户端存储中的数据结构和缓存策略，可能直接拿到完整数据。
- **Cookie 分析**: 查看 cookie 中的关键字段（token、session、userid），确认鉴权方式。

### 反爬对抗分析
- **指纹检测**: 检查页面是否调用 `navigator.webdriver`、`navigator.plugins`、`canvas fingerprint` 等检测手段，针对性配置绕过策略。
- **请求频率限制**: 通过逐步提高请求频率测试触发阈值，找到安全间隔。
- **验证码/风控**: 观察是否出现滑块、点选等验证，确认触发条件。
- **响应校验**: 对比正常响应和异常响应的差异（HTTP 状态码、响应体中的错误码、页面跳转等），建立异常识别规则。

### 实际案例参考
- 本项目通过 `_analyze_items.py` 分析 `data-dir`、`data-note-type`、`data-entry-type` 等属性来区分文件和文件夹。
- 通过 `_analyze_icons.py` 分析 `.file-icon-wrap` 内部 SVG 的差异来辅助判断类型。
- 通过 `_analyze_tree.py` 分析侧边栏 `.sidebar-collapse-content` 的树形结构来理解文件夹层级。
- 通过 `_analyze_sidebar.py` 分析页面整体布局，定位导航/目录元素与文件列表的关系。