"""
有道云笔记批量导出工具（CloakBrowser 版）
=========================================
只导出"我的文件夹"根目录下的全部笔记（含子文件夹递归）。

用法:
    python scripts/youdao_export_cloak.py --list                          # 只列出根目录结构
    python scripts/youdao_export_cloak.py                                 # 导出全部
    python scripts/youdao_export_cloak.py --start 0 --count 2             # 导出根目录下前 2 个项目
    python scripts/youdao_export_cloak.py --folder "Python"               # 只导出根目录下指定名称的项目
    python scripts/youdao_export_cloak.py --output ./export               # 指定输出目录

登录状态:
    用户数据目录自动保存在 cloak_user_data/ 下，首次登录后下次自动保持登录。
"""

import argparse
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from cloakbrowser.browser import ensure_binary
from playwright.sync_api import sync_playwright

# 代码块格式修复工具
from fix_code_format import fix_markdown

# ============================================================
# 调试日志（仅写文件，不干扰终端输出）
# ============================================================
LOG_FILE = Path(__file__).parent.parent / "logs" / "debug_export.log"


def log(msg):
    """写日志到文件，不在终端显示"""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def log_clear():
    try:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
    except Exception:
        pass


# ============================================================
# 配置
# ============================================================
DEFAULT_WORKSPACE = Path(__file__).parent.parent / "有道云笔记"
USER_DATA_DIR = Path(__file__).parent.parent / "cloak_user_data"
YOUDAO_URL = "https://note.youdao.com/web/"

# ============================================================
# 浏览器管理
# ============================================================
def create_browser():
    """启动 CloakBrowser（通过 launch_persistent_context 持久化用户数据）"""
    print("[1/4] 启动 CloakBrowser...")
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    pw = sync_playwright().start()
    binary_path = ensure_binary()

    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(USER_DATA_DIR),
        headless=False,
        executable_path=binary_path,
        args=["--no-first-run"],
        viewport={"width": 1440, "height": 900},
        no_viewport=False,
    )

    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page


def wait_for_login(page):
    """等待用户在浏览器中手动登录（自动检测，无需按回车）"""
    print("\n" + "=" * 60)
    print("请在打开的浏览器窗口中完成登录操作")
    print("脚本会自动检测登录状态，无需手动按回车。")
    print("=" * 60)

    max_wait = 300
    for i in range(max_wait):
        time.sleep(1)
        try:
            current_url = page.url
            if "file/" in current_url and "login" not in current_url.lower():
                print(f"\n  检测到登录成功！")
                return
            sidebar = page.locator(".sidebar-collapse-content-item").first
            if sidebar.count() > 0:
                print(f"\n  检测到登录成功（侧边栏已加载）！")
                return
        except Exception:
            pass

        if i % 30 == 0 and i > 0:
            try:
                print(f"  等待登录中... 已等待 {i} 秒 (URL: {page.url[:60]})")
            except:
                print(f"  等待登录中... 已等待 {i} 秒")
    print("\n  [WARN] 等待超时，请检查是否已登录")


def close_browser(pw):
    """安全关闭 Playwright"""
    try:
        pw.stop()
    except Exception as e:
        print(f"[WARN] 关闭浏览器时出错: {e}")


# ============================================================
# 页面交互
# ============================================================
def ensure_root(page):
    """确保处于"我的文件夹"根目录，返回根目录 URL"""
    log(f"ensure_root: 开始定位根目录")

    # 先导航到目标域名，清除 localStorage 中上次的导航状态，再重新加载
    page.goto(YOUDAO_URL, wait_until="domcontentloaded")
    page.evaluate("""() => {
        try { localStorage.removeItem('yn:all:last_navigation'); } catch(e) {}
    }""")
    # 重新加载页面，让 SPA 以干净状态启动
    page.goto(YOUDAO_URL, wait_until="domcontentloaded")
    log(f"ensure_root: goto 完成, URL={page.url[:80]}")
    page.wait_for_timeout(1500)

    # 通过侧边栏点击"我的文件夹"定位根目录
    try:
        page.wait_for_selector(".sidebar-collapse-content-item", state="attached", timeout=10000)
        log(f"ensure_root: 侧边栏已加载")
        time.sleep(1)

        # 用 JS 查找并点击"我的文件夹"
        clicked = page.evaluate("""() => {
            const rootTitle = document.querySelector('.tree-title.root-title');
            if (rootTitle) { rootTitle.click(); return true; }
            const items = document.querySelectorAll('.sidebar-collapse-content-item');
            for (const el of items) {
                if (el.textContent.includes('我的文件夹')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            log(f"ensure_root: 点击'我的文件夹'成功")
            page.wait_for_timeout(2000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass
            log(f"ensure_root: 点击后 URL={page.url[:80]}")
        else:
            log(f"ensure_root: 未找到'我的文件夹'，可能已在根目录")

        # 等待文件列表出现
        page.wait_for_selector("li.file-item", timeout=10000)
        log(f"ensure_root: 文件列表已出现, URL={page.url[:80]}")
    except Exception as e:
        log(f"ensure_root: WARN 异常: {e}")
        try:
            page.wait_for_selector("li.file-item", timeout=10000)
        except:
            pass

    return page.url


def list_items(page):
    """获取当前目录下所有笔记的名称"""
    items = page.locator("li.file-item").all()
    result = []
    for item in items:
        name_el = item.locator(".file-name")
        name = name_el.text_content().strip() if name_el.count() > 0 else "无标题"
        result.append(name)
    return result


def _find_sidebar_container(page, folder_name):
    """在侧边栏中找到指定文件夹的子节点容器，返回 JS 表达式。
    当多个文件夹同时展开时，不能用 querySelector('.tree-title.expanded')，
    必须按名称精确匹配。"""
    if folder_name:
        # 在多个 .expanded 中按名称精确匹配
        return page.evaluate("""(name) => {
            const allExpanded = document.querySelectorAll('.tree-title.expanded');
            for (const title of allExpanded) {
                if (title.textContent.trim() === name) {
                    const container = title.nextElementSibling;
                    if (container && container.children.length > 0) {
                        return Array.from(container.children)
                            .filter(c => c.matches && c.matches('.filetree-item'))
                            .map(c => {
                                const t = c.querySelector('.tree-title');
                                return t ? t.textContent.trim() : '';
                            })
                            .filter(Boolean);
                    }
                    return [];
                }
            }
            return [];
        }""", folder_name)
    else:
        # 根目录：用 .root-title
        return page.evaluate("""() => {
            const rootTitle = document.querySelector('.tree-title.root-title');
            if (!rootTitle) return [];
            const container = rootTitle.nextElementSibling;
            if (!container) return [];
            return Array.from(container.children)
                .filter(c => c.matches && c.matches('.filetree-item'))
                .map(c => {
                    const t = c.querySelector('.tree-title');
                    return t ? t.textContent.trim() : '';
                })
                .filter(Boolean);
        }""")


def get_sidebar_sub_folders(page, current_folder_name=None):
    """从侧边栏树获取当前文件夹的直接子文件夹名称列表"""
    result = _find_sidebar_container(page, current_folder_name)
    log(f"get_sidebar_sub_folders(current={current_folder_name}): {len(result)} 个 -> {result}")
    return result


def click_sidebar_folder(page, folder_name, parent_folder_name=None):
    """点击侧边栏中指定名称的文件夹，进入该文件夹"""
    page.evaluate("""([name, parentName]) => {
        let container = null;
        if (parentName) {
            const allExpanded = document.querySelectorAll('.tree-title.expanded');
            for (const title of allExpanded) {
                if (title.textContent.trim() === parentName) {
                    container = title.nextElementSibling;
                    break;
                }
            }
        } else {
            const rootTitle = document.querySelector('.tree-title.root-title');
            if (rootTitle) container = rootTitle.nextElementSibling;
        }
        if (!container) return;
        for (const child of container.children) {
            if (child.matches && child.matches('.filetree-item')) {
                const title = child.querySelector('.tree-title');
                if (title && title.textContent.trim() === name) {
                    title.click();
                    return;
                }
            }
        }
    }""", [folder_name, parent_folder_name or ""])
    page.wait_for_timeout(2000)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except:
        pass
    try:
        page.wait_for_selector("li.file-item", timeout=10000)
    except:
        log(f"click_sidebar_folder: '{folder_name}' 可能为空文件夹，无 file-item")
        pass
    page.wait_for_timeout(500)


def click_sidebar_parent(page, current_folder_name):
    """在侧边栏中点击当前文件夹的父文件夹，返回上一级"""
    page.evaluate("""(name) => {
        const allExpanded = document.querySelectorAll('.tree-title.expanded');
        let expandedTitle = null;
        for (const title of allExpanded) {
            if (title.textContent.trim() === name) {
                expandedTitle = title;
                break;
            }
        }
        if (!expandedTitle) return;
        // 找到父 filetree-item
        const parentItem = expandedTitle.closest('.filetree-item')
            ?.parentElement?.closest('.filetree-item');
        if (parentItem) {
            const parentTitle = parentItem.querySelector(':scope > .tree-title');
            if (parentTitle) { parentTitle.click(); return; }
        }
        // 没有父级，点击"我的文件夹"回到根目录
        const items = document.querySelectorAll('.sidebar-collapse-content-item');
        for (const el of items) {
            if (el.textContent.includes('我的文件夹')) { el.click(); return; }
        }
    }""", current_folder_name)
    page.wait_for_timeout(2000)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except:
        pass
    try:
        page.wait_for_selector("li.file-item", timeout=10000)
    except:
        log(f"click_sidebar_parent: 返回上级后无 file-item（可能为空文件夹）")
        pass
    page.wait_for_timeout(500)


def double_click_item_by_index(page, index):
    """双击第 index 个项目，并返回操作后的状态"""
    items = page.locator("li.file-item").all()
    if index >= len(items):
        log(f"double_click: index={index} 超出范围, 共 {len(items)} 项")
        return None

    item = items[index]
    name = item.locator(".file-name").text_content().strip() if item.locator(".file-name").count() > 0 else "(无名称)"
    log(f"double_click: 开始双击 index={index} [{name}]")

    # 记录操作前的状态
    before_items = list_items(page)
    before_url = page.url
    log(f"double_click: 双击前 URL={before_url[:80]}, items={len(before_items)}")

    # 滚动到可见并双击
    try:
        item.scroll_into_view_if_needed()
        item.dblclick(timeout=5000)
        log(f"double_click: dblclick() 成功")
    except Exception as e:
        log(f"double_click: WARN 双击失败: {e}，尝试 JS 双击")
        item.evaluate("""(el) => {
            const e1 = new MouseEvent('dblclick', {bubbles: true, cancelable: true});
            el.dispatchEvent(e1);
        }""")

    # 等待 SPA 切换
    page.wait_for_timeout(1500)

    # 等待页面稳定
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
        log(f"double_click: networkidle 就绪")
    except:
        log(f"double_click: networkidle 超时")

    after_items = list_items(page)
    after_url = page.url
    has_editor = is_note_page(page)
    log(f"double_click: 双击后 URL={after_url[:80]}, has_editor={has_editor}, items={len(after_items)}")

    # 判断结果
    if after_items != before_items:
        log(f"double_click: -> 文件夹 (列表变化)")
        return {"type": "folder", "url": after_url, "items": after_items, "parent_url": before_url}
    elif has_editor:
        # 验证是否打开了正确的笔记（SPA 可能缓存上一个笔记的编辑器）
        actual_title = ""
        try:
            actual_title = page.evaluate("""() => {
                const ta = document.querySelector('textarea.css-4wnwuk, .top-input, input[placeholder*=\\'标题\\']');
                if (ta) return ta.value || '';
                return '';
            }""")
        except Exception:
            pass
        actual_title = actual_title.strip() if actual_title else ""
        log(f"double_click: 编辑器标题='{actual_title}', 期望='{name}'")

        # 如果编辑器标题不匹配说明是缓存的旧笔记，重新双击
        if actual_title and actual_title != name:
            log(f"double_click: WARN 缓存命中，等待后重新双击")
            page.wait_for_timeout(2000)
            try:
                item.scroll_into_view_if_needed()
                item.dblclick(timeout=5000)
            except Exception:
                item.evaluate("""(el) => {
                    const e1 = new MouseEvent('dblclick', {bubbles: true, cancelable: true});
                    el.dispatchEvent(e1);
                }""")
            page.wait_for_timeout(1500)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass
            after_url = page.url
            has_editor = is_note_page(page)
            log(f"double_click: 重试后 URL={after_url[:80]}, has_editor={has_editor}")

        return {"type": "note", "url": after_url, "items": after_items, "parent_url": before_url}
    elif after_url != before_url:
        log(f"double_click: -> 文件夹 (URL变化)")
        return {"type": "folder", "url": after_url, "items": after_items, "parent_url": before_url}
    else:
        # 完全没变化，可能是双击没生效，重试一次
        log(f"double_click: WARN 双击无响应，重试...")
        try:
            item.scroll_into_view_if_needed()
            item.dblclick(timeout=5000)
        except Exception:
            item.evaluate("""(el) => {
                const e1 = new MouseEvent('dblclick', {bubbles: true, cancelable: true});
                el.dispatchEvent(e1);
            }""")
        page.wait_for_timeout(1500)

        after_items2 = list_items(page)
        after_url2 = page.url
        has_editor2 = is_note_page(page)
        log(f"double_click: 重试后 URL={after_url2[:80]}, has_editor={has_editor2}")

        if after_items2 != before_items:
            return {"type": "folder", "url": after_url2, "items": after_items2, "parent_url": before_url}
        elif has_editor2:
            return {"type": "note", "url": after_url2, "items": after_items2, "parent_url": before_url}
        else:
            log(f"double_click: WARN 返回 unknown")
            return {"type": "unknown", "url": after_url2, "items": after_items2, "parent_url": before_url}


def is_note_page(page):
    """判断当前页面是否出现笔记编辑器 iframe"""
    return page.evaluate("""() => {
        const el = document.getElementById('bulb-editor') || document.getElementById('cache-md-editor');
        return !!el;
    }""")


def close_note_editor(page):
    """关闭 SPA 自动恢复打开的笔记编辑器，通过移除 URL 中的笔记 hash"""
    try:
        if is_note_page(page):
            log(f"go_to_url: SPA 恢复了笔记编辑器，通过 JS 移除笔记 hash")
            page.evaluate("""() => {
                const hash = window.location.hash;
                // 取最后一段，如果是笔记 ID 就移除
                const idx = hash.lastIndexOf('/');
                const last = hash.slice(idx + 1);
                if (last && /^[A-Z][A-Z0-9]+$/.test(last)) {
                    window.location.hash = hash.slice(0, idx + 1);
                }
            }""")
            page.wait_for_timeout(800)
            log(f"go_to_url: 编辑器已关闭")
    except Exception as e:
        log(f"go_to_url: 关闭编辑器异常: {e}")


def go_to_url(page, url):
    """导航到指定 URL 并等待文件列表就绪"""
    log(f"go_to_url: 导航到 {url[:80]}")
    page.goto(url, wait_until="domcontentloaded")
    log(f"go_to_url: goto 完成, 当前 URL={page.url[:80]}")
    page.wait_for_timeout(1000)
    try:
        # 等待文件列表出现（SPA 的编辑器 iframe 不会从 DOM 消失，只检查文件列表）
        page.wait_for_selector("li.file-item", timeout=10000)
        log(f"go_to_url: 文件列表已出现")
        page.wait_for_timeout(1000)
        log(f"go_to_url: 导航完成")
    except Exception as e:
        log(f"go_to_url: WARN 等待异常: {e}")

    # 关闭 SPA 自动恢复的笔记编辑器
    close_note_editor(page)


# ============================================================
# 内容提取
# ============================================================
def sanitize_filename(name):
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(" ._")
    return name or "untitled"


def extract_note_content(page):
    """提取笔记标题和原始 Markdown（含图片占位符）"""
    log(f"extract: 开始提取")
    title = ""
    md_content = ""
    img_urls = []

    # 等待编辑器完全加载
    try:
        page.wait_for_function(
            """() => {
                const iframe = document.getElementById('bulb-editor') ||
                               document.getElementById('cache-md-editor');
                return iframe && iframe.contentDocument && iframe.contentDocument.body;
            }""",
            timeout=10000,
        )
        log(f"extract: 编辑器 iframe 已加载")
    except:
        log(f"extract: WARN 编辑器 iframe 等待超时")

    # 提取标题
    try:
        title = page.locator("textarea.css-4wnwuk, .top-input, input[placeholder*='标题']").input_value()
        title = title.strip()
        log(f"extract: 标题='{title}'")
    except:
        log(f"extract: 标题为空")
        title = ""

    # 提取编辑器内部 HTML
    html = page.evaluate("""() => {
        const iframe = document.getElementById('bulb-editor') ||
                       document.getElementById('cache-md-editor');
        if (!iframe) return '';
        const doc = iframe.contentDocument || iframe.contentWindow.document;
        if (!doc || !doc.body) return '';
        const inner = doc.querySelector('.bulb-editor-inner');
        return inner ? inner.innerHTML : doc.body.innerHTML;
    }""")

    if html:
        log(f"extract: HTML 长度={len(html)}")
        md_content = html_to_markdown(html, img_urls)
        log(f"extract: Markdown 长度={len(md_content)}, 图片数={len(img_urls)}")
    else:
        log(f"extract: WARN 未获取到 HTML")

    # 过滤空笔记的编辑器模板文字
    if md_content and any(kw in md_content for kw in ["标题 1", "标题 2", "标题 3", "标题 4"]):
        ui_keywords = ["Bright", "white", "neat", "github", "Neutral", "mdn_like",
                       "dracula", "monokai", "hopscotch", "kuroir", "iplastic",
                       "类图", "状态图", "E-R图", "饼图", "用户旅程图", "更多"]
        ui_count = sum(1 for kw in ui_keywords if kw in md_content)
        if ui_count >= 3:
            log(f"extract: 检测到编辑器模板, 清空内容")
            md_content = ""

    return title, md_content, img_urls


# ============================================================
# HTML 转 Markdown
# ============================================================
def clean_text(text):
    if not text:
        return ""
    text = text.replace('\ufeff', '').replace('\u200b', '')
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()
    return text


def is_link_element(element):
    if not isinstance(element, Tag):
        return False
    if element.name == 'a':
        return True
    if element.get('data-block-type') == 'link':
        return True
    return False


def get_link_href(element):
    href = element.get('data-href') or element.get('href')
    return href.strip() if href else None


def inline_to_markdown(element, img_urls, in_link=False):
    parts = []
    for child in element.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif child.name == 'br':
            parts.append('\n')
        elif child.name == 'img':
            src = child.get('data-src') or child.get('src')
            if src:
                img_urls.append(src)
                idx = len(img_urls) - 1
                parts.append(f"<!--IMG:{idx}-->")
            else:
                parts.append("![图片]")
        elif child.name == 'table':
            parts.append(table_to_markdown(child, img_urls))
        elif isinstance(child, Tag):
            if in_link and is_link_element(child):
                text = inline_to_markdown(child, img_urls, in_link=True)
                parts.append(text)
            elif is_link_element(child):
                text = inline_to_markdown(child, img_urls, in_link=True)
                href = get_link_href(child)
                text = clean_text(text)
                if href and text:
                    parts.append(f"[{text}]({href})")
                elif href:
                    parts.append(f"<{href}>")
                else:
                    parts.append(text)
            else:
                text = inline_to_markdown(child, img_urls)
                classes = ' '.join(child.get('class', []))
                if 'bold' in classes or 'strong' in classes:
                    parts.append(f"**{text}**")
                elif 'italic' in classes:
                    parts.append(f"*{text}*")
                elif 'strikethrough' in classes:
                    parts.append(f"~~{text}~~")
                elif 'underline' in classes:
                    parts.append(f"<u>{text}</u>")
                elif 'code' in classes:
                    parts.append(f"`{text}`")
                else:
                    parts.append(text)
    return ''.join(parts)


def list_to_markdown(element, img_urls, list_type, indent=0):
    prefix = '  ' * indent
    lines = []
    item_index = 0
    for child in element.children:
        if isinstance(child, NavigableString):
            continue
        if child.get('data-block-type') == 'list-item':
            item_index += 1
            text = inline_to_markdown(child, img_urls)
            text = clean_text(text)
            if list_type == 'todo':
                marker = "- [ ]"
            elif list_type == 'ordered':
                marker = f"{item_index}."
            else:
                marker = "-"
            lines.append(f"{prefix}{marker} {text}")
            for nested in child.children:
                if isinstance(nested, NavigableString):
                    continue
                if nested.get('data-block-type') == 'list':
                    nested_type = nested.get('data-list-type', 'unordered')
                    nested_md = list_to_markdown(nested, img_urls, nested_type, indent + 1)
                    lines.append(nested_md.rstrip('\n'))
    return '\n'.join(lines) + '\n\n'


def table_to_markdown(table_element, img_urls):
    """将 HTML <table> 转换为 Markdown 表格"""
    rows = table_element.find_all('tr')
    if not rows:
        return ""

    md_rows = []
    for tr in rows:
        cells = tr.find_all(['td', 'th'])
        row = []
        for cell in cells:
            text = inline_to_markdown(cell, img_urls)
            text = clean_text(text)
            text = text.replace('|', '\\|')
            row.append(text)
        if row:
            md_rows.append(row)

    if not md_rows or not md_rows[0]:
        return ""

    col_count = max(len(row) for row in md_rows)
    for row in md_rows:
        while len(row) < col_count:
            row.append('')

    lines = []
    lines.append('| ' + ' | '.join(md_rows[0]) + ' |')
    lines.append('|' + '|'.join([' --- '] * col_count) + '|')
    for row in md_rows[1:]:
        lines.append('| ' + ' | '.join(row) + ' |')

    return '\n'.join(lines) + '\n\n'


def block_to_markdown(element, img_urls):
    block_type = element.get('data-block-type', '')
    if block_type == 'table' or element.name == 'table':
        return table_to_markdown(element, img_urls)
    if block_type == 'heading':
        level = element.get('data-heading-level', 'h1')
        prefix = '#' * int(level[1:]) if level.startswith('h') and level[1:].isdigit() else '#'
        text = inline_to_markdown(element, img_urls)
        text = clean_text(text)
        return f"{prefix} {text}\n\n" if text else ""
    elif block_type == 'paragraph':
        text = inline_to_markdown(element, img_urls)
        text = clean_text(text)
        return f"{text}\n\n" if text else ""
    elif block_type == 'list':
        list_type = element.get('data-list-type', 'unordered')
        return list_to_markdown(element, img_urls, list_type)
    elif block_type == 'todo':
        return list_to_markdown(element, img_urls, 'todo')
    elif block_type == 'code-block':
        text = inline_to_markdown(element, img_urls)
        text = clean_text(text)
        return f"```\n{text}\n```\n\n" if text else "```\n```\n\n"
    elif block_type == 'quote':
        text = inline_to_markdown(element, img_urls)
        text = clean_text(text)
        if not text:
            return ""
        return '\n'.join(f"> {line}" for line in text.split('\n')) + "\n\n"
    elif block_type == 'divider':
        return "---\n\n"
    elif block_type == 'image':
        img = element.find('img')
        if img:
            src = img.get('data-src') or img.get('src')
            if src:
                img_urls.append(src)
                idx = len(img_urls) - 1
                return f"<!--IMG:{idx}-->\n\n"
        return "![图片]\n\n"
    else:
        # 某些块可能包含嵌套的 <table>，直接提取转换
        table = element.find('table')
        if table:
            return table_to_markdown(table, img_urls)
        text = inline_to_markdown(element, img_urls)
        text = clean_text(text)
        return f"{text}\n\n" if text else ""


def html_to_markdown(html, img_urls):
    soup = BeautifulSoup(html, 'html.parser')
    inner = soup.find(class_='bulb-editor-inner') or soup
    md_parts = []
    for child in inner.children:
        if isinstance(child, NavigableString):
            continue
        md = block_to_markdown(child, img_urls)
        if md:
            md_parts.append(md)
    return ''.join(md_parts).strip()


# ============================================================
# 图片下载
# ============================================================
def download_image(url, context):
    """使用浏览器 cookies 下载图片"""
    try:
        cookies = context.cookies()
        cookie_dict = {c['name']: c['value'] for c in cookies}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://note.youdao.com/',
        }
        for attempt in range(3):
            try:
                resp = requests.get(url, cookies=cookie_dict, headers=headers, timeout=30)
                if resp.status_code == 200 and len(resp.content) > 100:
                    return resp.content, resp.headers.get('Content-Type', '')
            except Exception as e:
                if attempt < 2:
                    time.sleep(1)
                else:
                    pass
        return None, None
    except Exception:
        return None, None


# 图片文件头魔数映射
_IMG_MAGIC = {
    b'\x89PNG\r\n\x1a\n': 'png',
    b'\xff\xd8\xff': 'jpg',
    b'GIF87a': 'gif',
    b'GIF89a': 'gif',
    b'RIFF': 'webp',  # RIFF....WEBP
    b'BM': 'bmp',
}


def _detect_ext_from_bytes(data):
    """根据二进制头检测图片真实格式"""
    for magic, ext in _IMG_MAGIC.items():
        if data.startswith(magic):
            if ext == 'webp' and len(data) > 12 and data[8:12] == b'WEBP':
                return 'webp'
            if ext == 'webp':
                continue
            return ext
    return None


def process_images(md_content, img_urls, target_dir, safe_title, context):
    """下载图片并替换 Markdown 中的占位符"""
    if not img_urls:
        return md_content, 0

    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for i, url in enumerate(img_urls):
        content, content_type = download_image(url, context)
        if content:
            # 优先用二进制头检测真实格式，Content-Type 可能不准确
            ext = _detect_ext_from_bytes(content)
            if not ext:
                ext = content_type.split('/')[-1] if content_type and '/' in content_type else 'png'
            if ext not in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']:
                ext = 'png'
            img_name = f"{safe_title}_{i+1}.{ext}"
            img_path = target_dir / img_name
            with open(img_path, 'wb') as f:
                f.write(content)
            # URL 编码文件名，避免括号、中文等特殊字符破坏 markdown 图片语法
            encoded_name = urllib.parse.quote(img_name, safe='')
            md_content = md_content.replace(f"<!--IMG:{i}-->", f"![{img_name}]({encoded_name})")
            downloaded += 1
        else:
            md_content = md_content.replace(f"<!--IMG:{i}-->", "![图片下载失败]")
    return md_content, downloaded


# ============================================================
# 文件保存
# ============================================================
def save_note(target_dir, title, md_content, img_count):
    """保存 Markdown 笔记到指定目录"""
    safe_title = sanitize_filename(title)
    target_dir.mkdir(parents=True, exist_ok=True)

    md_path = target_dir / f"{safe_title}.md"
    content = f"# {title}\n\n{md_content}".strip() + "\n"

    # 修复代码块格式
    try:
        content = fix_markdown(content)
    except Exception as e:
        log(f"save_note: fix_markdown 异常: {e}")

    md_path.write_text(content, encoding="utf-8")
    return str(md_path), img_count


# ============================================================
# 递归导出
# ============================================================
def export_current_notes(page, output_dir, path_parts, folder_url, start=0, count=None,
                         target_name=None, depth=0):
    """导出当前文件夹下的所有笔记（不处理子文件夹）"""
    items = list_items(page)
    log(f"export_notes[depth={depth}]: items={items}")
    if not items:
        return 0

    total = len(items)
    end = total if count is None else min(start + count, total)
    exported = 0
    prefix = "  " * depth

    for i in range(start, end):
        if i >= total:
            break
        name = items[i]
        if target_name and depth == 0 and name != target_name:
            continue

        print(f"\n{prefix}[笔记 {i+1}/{total}] {name}")
        log(f"export_notes: >>> 处理 [{i}/{total}] '{name}' <<<")

        result = double_click_item_by_index(page, i)
        if result is None:
            print(f"{prefix}  [ERROR] 无法双击")
            log(f"export_notes: [ERROR] 无法双击 '{name}'")
            continue

        if result["type"] != "note":
            log(f"export_notes: WARN '{name}' 不是笔记, type={result['type']}")
            # 文件夹双击导致页面导航到了子文件夹，需要返回当前文件夹
            go_to_url(page, folder_url)
            continue

        title, md_raw, img_urls = extract_note_content(page)
        if not title:
            title = name

        safe_title = sanitize_filename(title)
        target_dir = output_dir / Path(*[sanitize_filename(p) for p in path_parts])
        log(f"export_notes: 下载图片 {len(img_urls)} 张")
        md_content, img_count = process_images(md_raw, img_urls, target_dir, safe_title, page.context)

        print(f"{prefix}  标题: {title}")
        print(f"{prefix}  图片: {img_count}/{len(img_urls)} 张")

        md_path, _ = save_note(target_dir, title, md_content, img_count)
        log(f"export_notes: 已保存 {md_path}")
        print(f"{prefix}  保存: {md_path}")
        exported += 1

        # 返回文件夹视图
        log(f"export_notes: '{name}' 完成, 返回文件夹")
        go_to_url(page, folder_url)

    return exported


def export_recursive(page, output_dir, start=0, count=None, target_name=None,
                     depth=0, path_parts=None):
    """递归导出当前文件夹的笔记和子文件夹，按目录树结构保存。"""
    if path_parts is None:
        path_parts = []

    prefix = "  " * depth
    exported = 0

    # 保存当前文件夹 URL，用于返回
    folder_url = page.url

    # 1. 导出当前文件夹下的笔记（根目录 depth=0 不导出，因为"我的文件夹"根目录下没有笔记）
    if depth > 0:
        log(f"export[depth={depth}]: 开始导出笔记, path={path_parts}")
        note_count = export_current_notes(
            page, output_dir, path_parts, folder_url,
            start=start if depth == 0 else 0,
            count=count if depth == 0 else None,
            target_name=target_name if depth == 0 else None,
            depth=depth,
        )
        exported += note_count

    # 2. 获取子文件夹列表
    parent_name = path_parts[-1] if path_parts else None
    sub_folders = get_sidebar_sub_folders(page, parent_name)
    log(f"export[depth={depth}]: 子文件夹={sub_folders}")

    if not sub_folders:
        return exported

    # 3. 递归处理每个子文件夹
    for sf_name in sub_folders:
        # 如果指定了 target_name 且当前是根目录，检查是否匹配
        if target_name and depth == 0 and sf_name != target_name:
            continue

        print(f"\n{prefix}[文件夹] {sf_name}/")
        log(f"export: >>> 进入文件夹 '{sf_name}' <<<")

        click_sidebar_folder(page, sf_name, parent_name)

        sub_exported = export_recursive(
            page, output_dir,
            start=0, count=None, target_name=None,
            depth=depth + 1,
            path_parts=path_parts + [sf_name],
        )
        exported += sub_exported

        # 返回父文件夹
        log(f"export: '{sf_name}' 完成, 返回父文件夹")
        print(f"{prefix}  <- 返回上级...")
        click_sidebar_parent(page, sf_name)

    return exported


# ============================================================
# 主流程
# ============================================================
def main():
    log_clear()
    log("========== 有道云笔记导出开始 ==========")
    parser = argparse.ArgumentParser(description="有道云笔记批量导出（CloakBrowser 版）")
    parser.add_argument("--start", type=int, default=0, help="从根目录第几个项目开始（0-based）")
    parser.add_argument("--count", type=int, default=None, help="处理多少个项目（默认全部）")
    parser.add_argument("--folder", type=str, default=None, help="只导出根目录下指定名称的项目")
    parser.add_argument("--list", action="store_true", help="只列出根目录项目")
    parser.add_argument("--output", type=str, default=None, help="输出目录（默认在 有道云笔记/ 下创建日期子目录）")
    args = parser.parse_args()

    if args.output:
        output_dir = Path(args.output)
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = DEFAULT_WORKSPACE / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"main: 输出目录={output_dir}")

    pw, context, page = create_browser()
    log(f"main: 浏览器已启动")

    try:
        # ---- 打开网页并确保登录 ----
        log(f"main: 打开有道云笔记")
        print("\n[2/4] 打开有道云笔记网页版...")
        page.goto(YOUDAO_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        log(f"main: 初始导航 URL={page.url[:80]}")

        if "login" in page.url.lower() or page.locator(".sidebar-collapse-content-item").count() == 0:
            log(f"main: 需要登录")
            wait_for_login(page)
        else:
            print("  检测到已登录状态")
            log(f"main: 已登录")

        # ---- 确保在我的文件夹根目录 ----
        print("\n[3/4] 定位到'我的文件夹'根目录...")
        root_url = ensure_root(page)
        log(f"main: 根目录 URL={root_url}")

        root_items = list_items(page)
        log(f"main: 根目录文件列表 {len(root_items)} 项: {root_items}")

        # 获取侧边栏文件夹列表
        root_folders = get_sidebar_sub_folders(page)
        log(f"main: 根目录文件夹 {len(root_folders)} 项: {root_folders}")

        print(f"  根目录下共有 {len(root_folders)} 个文件夹")
        for name in root_folders:
            print(f"    [文件夹] {name}/")

        if args.list:
            log(f"main: --list 列出目录")
            print("\n[完成] 仅列出目录结构")
            close_browser(pw)
            return

        if args.folder and args.folder not in root_folders:
            print(f"\n[ERROR] 根目录下未找到文件夹 '{args.folder}'")
            print(f"  可用文件夹: {', '.join(root_folders)}")
            close_browser(pw)
            return

        # ---- 开始导出 ----
        log(f"main: 开始导出 (start={args.start}, count={args.count}, folder={args.folder})")
        print("\n[4/4] 开始导出笔记...")
        total_exported = export_recursive(
            page, output_dir,
            start=args.start,
            count=args.count,
            target_name=args.folder,
            depth=0,
        )

        log(f"main: 导出完成, 共计 {total_exported} 篇")
        print(f"\n{'=' * 60}")
        print(f"[完成] 导出完成!")
        print(f"  成功导出: {total_exported} 篇笔记")
        print(f"  输出目录: {output_dir}")
        print(f"{'=' * 60}")

    finally:
        log(f"main: 关闭浏览器")
        close_browser(pw)
    log("========== 有道云笔记导出结束 ==========")


if __name__ == "__main__":
    main()
