---
name: tiger-youdao-note-exporter
description: 批量导出有道云笔记中的笔记到本地 Markdown 文件，包含图片下载和代码块格式修复。当用户需要导出有道云笔记、从有道云迁移到本地 Markdown、或下载带有代码块和图片的笔记时使用。
when_to_use: 用户提到导出 有道云笔记 / Youdao / YNote 笔记、转换有道云笔记本、备份有道云内容、或运行 youdao_export_cloak.py 脚本时
---

# 有道云笔记导出工具

将"我的文件夹"下的全部笔记从有道云笔记网页版导出到本地 Markdown 文件，保持原始目录结构。

## 前置条件

- Python 3.12+ 已安装
- 安装依赖：`pip install requests beautifulsoup4 playwright cloakbrowser`

## 导出流程

1. 切换到项目根目录：
   ```
   cd d:\Code\Skills\tiger-youdao-note-exporter
   ```

2. 运行导出脚本：
   ```
   python scripts/youdao_export_cloak.py
   ```

   浏览器窗口会自动打开。如需登录，用户需扫码或用账号密码登录。脚本会自动检测登录状态，无需手动按键。

3. 导出完成后，检查 `有道云笔记/` 下对应日期目录中的输出文件。

### 常用选项

| 命令 | 说明 |
|------|------|
| `python scripts/youdao_export_cloak.py --list` | 列出根目录结构（不导出） |
| `python scripts/youdao_export_cloak.py` | 导出全部笔记 |
| `python scripts/youdao_export_cloak.py --folder "Python"` | 只导出指定文件夹 |
| `python scripts/youdao_export_cloak.py --start 0 --count 2` | 导出前 2 个项目 |
| `python scripts/youdao_export_cloak.py --output D:\backup` | 指定输出目录（默认在 `有道云笔记/` 下创建日期子目录） |

## 脚本执行流程

对每个笔记执行以下操作：
1. 在文件列表中双击打开笔记编辑器
2. 从编辑器 iframe 中提取 HTML 内容
3. 将 HTML 转换为 Markdown 格式
4. 下载嵌入的图片并更新本地引用
5. 修复代码块格式（添加 ``` 标记、检测语言、恢复换行符）
6. 保存为 `.md` 文件，保持原始目录结构

## 文件位置

- 导出脚本：`scripts/youdao_export_cloak.py`
- 代码块修复：`scripts/fix_code_format.py`（导出时自动调用）
- 浏览器用户数据：`cloak_user_data/`（自动创建，持久化登录状态）
- 日志：`logs/debug_export.log`
- 输出目录：`有道云笔记/YYYY-MM-DD/`（默认，按日期分目录）

## 注意事项

- 首次运行需要手动登录（扫码或账号密码）。后续运行复用已保存的会话。
- `cloak_user_data/`、`有道云笔记/`、`logs/`、`backup/` 已被 .gitignore 排除。
- 已导出的笔记会覆盖同名的旧文件。图片已存在则不会重复下载。
- 导出过程中可按 Ctrl+C 中断，已保存的笔记不会丢失。