"""
Markdown 代码块格式修复工具。
整合了代码块发现（fix_code_blocks）和换行修复（fix_code_linebreaks）功能。

用途：
  有道云笔记导出的 Markdown 文件存在两种格式问题：
  1. 代码块未被 ``` 包裹，或使用了无效的 ````自动换行` 标记
  2. 代码行被挤压在一行内，丢失了换行符

用法：
  命令行: python scripts/fix_code_format.py <markdown文件路径>
  模块导入: from scripts.fix_code_format import fix_markdown
"""
import re
import sys


# ============================================================
# 语言检测 —— 通过关键词匹配来判断代码块的语言
# ============================================================
# 每个语言关键词列表按优先级排列。
# 命中计分最高的语言类型会被选定为代码块的 ```lang 标签。
# 如果没有任何语言得分明显领先，则返回 None，由调用方决定默认值。

_PY_KEYWORDS = ['def ', 'class ', 'import ', 'from ', '@', 'self.', 'tornado',
                'yield', 'asyncio', 'with ', 'elif ', 'else:', 'try:', 'except',
                'finally:', 'raise ', 'in ', 'super()', '__init__']
_JS_KEYWORDS = ['function', 'var ', 'let ', 'const ', '=>', 'document.', 'window.',
                '$', 'val()', 'ajax', 'prototype.', 'addEventListener', 'querySelector']
_CPP_KEYWORDS = ['#include', 'PYBIND11', 'py::', 'std::', '::', 'int ', 'float ',
                 'double ', 'void ', 'char ', 'bool ', 'struct ', 'namespace ',
                 'public:', 'private:', 'protected:', 'virtual ', 'const ',
                 '->', 'nullptr', 'new ', 'delete ', 'template', 'typename']
_BASH_KEYWORDS = ['sudo ', 'apt-get', 'apt ', 'wget ', 'curl ', 'tar ', './configure',
                  'make', 'pip ', 'pip3', 'python3', 'll ', 'ls ', 'cd ', 'ln ', 'rm ',
                  'mv ', 'grep ', 'sed ', 'awk ', 'echo ', 'git ', 'docker ', 'npm ',
                  'export ', 'source ', '//', '>>', '2>&1', 'systemctl']


def _detect_language(code):
    """
    通过关键词命中计分判断代码块的语言。
    比较 bash / cpp / python / javascript 四种语言的得分，
    得分最高的且明显领先其他语言时才返回对应的语言标签。
    如果胜负不明显（例如混有少量 Python 关键词的 C++ 代码），
    返回 None 让调用方处理。
    """
    py_score = sum(1 for kw in _PY_KEYWORDS if kw in code)
    js_score = sum(1 for kw in _JS_KEYWORDS if kw in code)
    cpp_score = sum(1 for kw in _CPP_KEYWORDS if kw in code)
    bash_score = sum(1 for kw in _BASH_KEYWORDS if kw in code)
    if bash_score > py_score and bash_score > js_score and bash_score > cpp_score:
        return 'bash'
    if cpp_score > py_score and cpp_score > js_score and cpp_score > bash_score:
        return 'cpp'
    if py_score > js_score and py_score > cpp_score:
        return 'python'
    if js_score > py_score and js_score > cpp_score:
        return 'javascript'
    return None


# ============================================================
# 阶段 1: 代码块发现（添加 ``` 标记）
#   扫描 Markdown 文件的每一行，识别出未被 ``` 包裹的代码行，
#   自动检测代码的语言并添加 ``` 标记。
# ============================================================

def _is_chinese(s):
    """判断一行是否以中文字符开头，用于区分代码与中文说明文字"""
    return bool(re.match(r'^[\u4e00-\u9fff]', s))


def _is_numbered(s):
    """判断是否是有序列表项（如 "1. ", "2、", "3) "），不是代码"""
    return bool(re.match(r'^\d+[\.\、\)\s]', s))


def _is_table(s):
    """判断是否是 Markdown 表格行（以 | 开头且包含多个 |）"""
    return s.startswith('|') and '|' in s[1:]


def _is_bold(s):
    """判断是否是加粗文本（**...**），不是代码"""
    return s.startswith('**') and '**' in s[1:]


def _is_bash_line(s):
    """
    判断一行是否看起来像 shell 命令。
    识别策略：
    - 以常见命令名开头（sudo, apt-get, wget, tar, git 等）
    - 命令名 + 参数格式（如 python3.6 -V）
    - shebang 注释（// 开头的 shell 注释）
    - 管道操作（如 | grep, | awk 等）
    """
    if not s:
        return False
    bash_cmds = [
        # 系统包管理
        'sudo ', 'apt-get', 'apt ', 'wget ', 'curl ', 'tar ', './configure',
        # 编译构建
        'make', 'pip ', 'pip3', 'pip2', 'python3', 'python2',
        # 文件操作
        'll ', 'ls ', 'cd ', 'ln ', 'rm ', 'mv ', 'cp ', 'mkdir ', 'chmod ', 'chown ',
        # 文本处理
        'grep ', 'sed ', 'awk ', 'echo ', 'cat ', 'head ', 'tail ', 'less ', 'more ',
        # 开发工具
        'git ', 'docker ', 'npm ', 'node ', 'yarn ', 'cnpm ',
        # 环境变量
        'export ', 'source ', 'alias ', 'unset ',
        # 系统服务
        'systemctl ', 'service ', 'journalctl ',
        # 进程管理
        'ps ', 'kill ', 'top ', 'htop ',
        # 远程连接
        'ssh ', 'scp ', 'rsync ',
        # 网络配置
        'ifconfig ', 'ip ', 'netstat ',
        # 路径查找
        'env ', 'which ', 'whereis ', 'type ',
        # 重定向
        '>>', '>|', '2>&1', '&>',
        # Windows 路径
        '.\\', '..\\',
    ]
    if any(s.startswith(cmd) for cmd in bash_cmds):
        return True
    # 命令名 + 参数（如 python3.6 -V, pip3.6 -V）
    if re.match(r'^[a-z][a-z0-9_.-]*\s+-[a-zA-Z]', s):
        return True
    # // 注释（shell 风格）
    if s.startswith('//'):
        return True
    # 管道/重定向
    if '|' in s and any(cmd.replace(' ', '') in s for cmd in ['grep', 'cat', 'head', 'tail', 'less', 'more', 'sort', 'uniq', 'wc', 'awk', 'sed']):
        return True
    return False


def _is_code_line(s):
    """
    判断一行是否看起来像代码（而非自然语言）。
    支持的代码类型：
    - Python: def, class, import, from, @, async, with, try/except, for/while, if/elif/else
    - Python REPL: >>>, ...
    - JavaScript: function, var/let/const, console.xxx, if()
    - C/C++: #include, PYBIND11, py::, std::, int/float/void, struct, namespace
    - 通用: 缩进行, 条件表达式(==, !=, =>), 赋值语句
    """
    if not s:
        return False
    # Python 关键字（函数定义、类定义、导入、装饰器、异步、异常处理）
    if re.match(r'^(def |class |import |from |@|async |await |with |try:|except|finally:|raise |yield |return |print\b)', s):
        return True
    # Python 控制流关键字
    if re.match(r'^(for |while |if |elif |else:|pass|break|continue|del )', s):
        return True
    # 变量赋值或函数调用（如 x = 1, foo.bar()）
    if re.match(r'^[a-z_][a-z0-9_\.]*\s*[=\(\[]', s):
        return True
    # Python 交互式解释器提示符
    if s.startswith(('>>> ', '... ')):
        return True
    # JavaScript 函数/变量声明/控制流
    if re.match(r'^(if\s*\(|function |var |let |const |console\.)', s):
        return True
    # 缩进代码（通常表示代码块内部）
    if s.startswith(('    ', '\t')):
        return True
    # 以 # 开头的非标题/非加粗行（通常是代码注释）
    if s.startswith('#') and not s.startswith('# '):
        return True
    # 条件/比较运算符（常见于代码行）
    if '==' in s or '!=' in s or '=>' in s:
        return True
    # ----- C/C++/pybind11 特征 -----
    # 头文件包含
    if s.startswith('#include'):
        return True
    # pybind11 宏/命名空间
    if s.startswith('PYBIND11_') or s.startswith('py::'):
        return True
    # C++ 类型关键字（作为函数返回类型或变量类型）
    if re.match(r'^(int |float |double |char |void |bool |long |short |unsigned |struct |enum |namespace )', s):
        return True
    # C++ 标准库命名空间
    if re.match(r'^std::', s):
        return True
    # 作用域解析操作符（如 ClassName::method）
    if re.match(r'^[a-z_][a-z0-9_]*\s*::', s):
        return True
    # 类/结构体/枚举的结尾（如 }; 或 }）
    if re.match(r'^};?\s*$', s):
        return True
    return False


def _collect_code_block(lines, start_idx, min_lines=2):
    """
    从 start_idx 开始收集连续的代码行，直到遇到非代码行为止。
    返回 (code_lines, end_index) 元组，或者 None（如果收集到的行数不足 min_lines）。

    收集规则：
    - 空行：跳过，继续向后收集（代码块内部可以有空白行）
    - 中文行：为了安全立即停止（中文通常不是代码）
    - 编号列表项：停止（编号列表不是代码块）
    - 表格行：停止（Markdown 表格不是代码块）
    - 加粗文本：停止（除非是代码行，比如 **key**=value 这种）
    - 分隔线（---, ***）：停止
    - 代码行：继续收集
    - 其他行：如果看起来像标识符/表达式，也继续收集（兜底策略）
    """
    code_lines = [lines[start_idx]]
    j = start_idx + 1
    while j < len(lines):
        line = lines[j]
        s = line.strip()
        # 空行：跳过（代码块允许空行）
        if s == '':
            code_lines.append(line)
            j += 1
            continue
        # 遇到中文行，停止（除非是代码行，如 # 注释）
        if _is_chinese(s) and not _is_code_line(s):
            break
        # 编号列表，停止
        if _is_numbered(s):
            break
        # 表格，停止
        if _is_table(s):
            break
        # 加粗文本，停止（除非是代码行）
        if _is_bold(s) and not _is_code_line(s):
            break
        # 分隔线，停止
        if s.startswith('---') or s.startswith('***'):
            break
        # 代码行或大括号/括号结尾行，继续
        if _is_code_line(s) or s.startswith(('    ', '\t', '}', '{', ');')):
            code_lines.append(line)
            j += 1
        else:
            # 兜底：如果看起来像标识符或表达式，继续
            if re.match(r'^[a-zA-Z_][a-zA-Z0-9_\.\(\)\"\'\[\]]', s):
                code_lines.append(line)
                j += 1
            else:
                break
    if len(code_lines) >= min_lines:
        return (code_lines, j)
    return None


def _add_code_blocks(content):
    """
    核心函数：为未包裹的代码添加 ``` 标记。
    处理流程：
    1. 清理已有的正确 ``` 标记（独立行），避免重复包裹
    2. 逐行扫描，识别各种代码模式：
       - ``自动换行<code> 前缀（有道云笔记特有的格式残留，2 个反引号）
       - `任意文本`自动换行` 前缀（如 `JavaScript`自动换行`、`Plain Text`自动换行`）
       - Python 关键字开头（def, class, import 等）
       - Python 交互式代码（>>> 开头）
       - JavaScript if 语句
       - bash/shell 命令
       - 变量赋值语句
       - 缩进代码
       - MQTT 相关导入
       - # 注释行
       - print() 语句
    3. 清理多余空行
    """
    # 清理已有 ``` 标记（只移除独立行标记，不处理 inline 代码）
    # 注意：``自动换行<code> 这种格式不会被清理，由后续处理逻辑处理
    content = re.sub(r'^```[a-zA-Z]*\s*$', '', content, flags=re.MULTILINE)  # 开标记: ```python
    content = re.sub(r'^```\s*$', '', content, flags=re.MULTILINE)           # 闭标记: ```
    content = re.sub(r'\n{3,}', '\n\n', content)                             # 清理多余空行

    lines = content.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ----- 处理 ``自动换行<code> -----
        # 有道云笔记导出时，有时会将代码标记为 ``自动换行<code> 格式。
        # 这是 2 个反引号 + "自动换行" + 代码，没有闭合标记。
        # 例如: ``自动换行PYBIND11_MODULE (libcppex, m) { ... }
        backtick_prefix = re.match(r'^``自动换行(.+)', line)
        if backtick_prefix:
            code_content = backtick_prefix.group(1).strip()
            if code_content:
                # 自动检测语言，C++ 代码默认标记为 cpp
                lang = _detect_language(code_content) or 'cpp'
                result.append(f'```{lang}')
                result.append(code_content)
                result.append('```')
                i += 1
                continue

        # ----- 处理 ``自动换行<code>`` -----
        # 与上一种类似，但有闭合反引号（首尾各 2 个）。
        # 例如: ``自动换行class Matrix { ... };``
        inline_match = re.match(r'^``自动换行(.*?)``\s*$', line)
        if inline_match:
            code_content = inline_match.group(1).strip()
            if code_content:
                lang = _detect_language(code_content) or 'cpp'
                result.append(f'```{lang}')
                result.append(code_content)
                result.append('```')
                i += 1
                continue

        # ----- 处理 `任意文本`自动换行` 前缀 -----
        # 有道云笔记另一种格式残留：`JavaScript`自动换行`<code>
        # 或 `Plain Text`自动换行`<code>。
        # 这种格式把代码和语言名称混在一起，需要提取代码部分。
        # 可以跨多行收集（直到遇到另一个 `自动换行 标记或空行）。
        prefix_match = re.match(r'^`[^`]+`自动换行`?(.*)', line)
        if prefix_match:
            code_content = prefix_match.group(1)
            code_lines = [code_content]
            j = i + 1
            while j < len(lines):
                nl = lines[j]
                if '`自动换行' in nl:
                    break
                ns = nl.strip()
                if ns == '':
                    break
                if _is_chinese(ns) and not _is_code_line(ns):
                    break
                if _is_table(ns):
                    break
                code_lines.append(nl)
                j += 1
            full_code = ''.join(code_lines)
            lang = _detect_language(full_code) or 'python'
            result.append(f'```{lang}')
            result.append(full_code)
            result.append('```')
            i = j
            continue

        # ----- Python 代码块 -----
        # 以 Python 关键字开头的行，使用 collect_code_block 收集连续代码行
        if re.match(r'^(def |class |import |from |@|async |await |with |try:|except|finally:|for |while |if |elif |else:|raise |yield |return )', stripped):
            block = _collect_code_block(lines, i)
            if block:
                code_lines, end = block
                result.append('```python')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # ----- Python 交互式代码 -----
        # >>> 和 ... 是 Python REPL 的提示符
        if stripped.startswith('>>> ') or stripped.startswith('... '):
            block = _collect_code_block(lines, i)
            if block:
                code_lines, end = block
                result.append('```python')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # ----- JavaScript 代码块 -----
        # 以 if(...) 开头且包含 == 或 !=
        if re.match(r'^if\s*\(', stripped) and ('==' in stripped or '!=' in stripped):
            block = _collect_code_block(lines, i, min_lines=3)
            if block:
                code_lines, end = block
                result.append('```javascript')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # ----- bash/shell 命令代码块 -----
        # 收集连续的 shell 命令（跳过空行），至少 2 行才形成代码块
        if _is_bash_line(stripped):
            bash_lines = [line]
            j = i + 1
            while j < len(lines):
                nl = lines[j]
                ns = nl.strip()
                if ns == '':
                    bash_lines.append(nl)
                    j += 1
                    continue
                if _is_chinese(ns):
                    break
                if _is_numbered(ns):
                    break
                if _is_bold(ns):
                    break
                if _is_bash_line(ns):
                    bash_lines.append(nl)
                    j += 1
                elif _is_code_line(ns):
                    break
                else:
                    # 兜底：有些命令可能被误判，继续收集
                    if ns.startswith(('sudo', 'apt', 'pip', 'python', '//')):
                        bash_lines.append(nl)
                        j += 1
                    else:
                        break
            # 清理尾部空行
            while bash_lines and bash_lines[-1].strip() == '':
                bash_lines.pop()
            if len(bash_lines) >= 2:
                result.append('```bash')
                result.extend(bash_lines)
                result.append('```')
                i = j
                continue

        # ----- 变量赋值语句 -----
        # 如 x = 1, foo = bar() 等
        # 排除中文行和编号行
        if re.match(r'^[a-z_][a-z0-9_]*\s*=\s*', stripped) and not _is_chinese(stripped) and not _is_numbered(stripped):
            block = _collect_code_block(lines, i)
            if block:
                code_lines, end = block
                result.append('```python')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # ----- 缩进代码块 -----
        # 以 4 个空格或制表符开头的行，通常是代码块内部内容
        if stripped.startswith(('    ', '\t')) and len(stripped) > 4:
            block = _collect_code_block(lines, i)
            if block:
                code_lines, end = block
                # 检查是否有 JavaScript 特征，用于区分语言
                has_js = any('$(' in l or 'function' in l or 'var ' in l or 'let ' in l or 'const ' in l for l in code_lines)
                lang = 'javascript' if has_js else 'python'
                result.append(f'```{lang}')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # ----- MQTT 相关代码 -----
        # 特例：paho-mqtt 库的导入语句
        if stripped.startswith('import paho') or stripped.startswith('from paho'):
            block = _collect_code_block(lines, i)
            if block:
                code_lines, end = block
                result.append('```python')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # ----- # 注释行 -----
        # 以 # 开头但不是 ## 标题或 # 加粗文本的行
        # 注意：排除 # 后跟空格的行（通常是 Markdown 标题，如 # 标题）
        if stripped.startswith('#') and not stripped.startswith('# ') and not stripped.startswith('##'):
            block = _collect_code_block(lines, i)
            if block:
                code_lines, end = block
                result.append('```python')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # ----- print() 语句 -----
        if stripped.startswith('print('):
            block = _collect_code_block(lines, i)
            if block:
                code_lines, end = block
                result.append('```python')
                result.extend(code_lines)
                result.append('```')
                i = end
                continue

        # 非代码行，直接输出
        result.append(line)
        i += 1

    new_content = '\n'.join(result)
    # 清理多余空行（最多 2 个连续空行）
    new_content = re.sub(r'\n{3,}', '\n\n', new_content)
    # 清理 ``` 和空行之间的多余空白
    new_content = re.sub(r'```\n\n+', '```\n', new_content)
    new_content = re.sub(r'\n\n+```', '\n```', new_content)
    return new_content


# ============================================================
# 阶段 2: 代码块换行修复
#   有道云笔记导出的代码块有时会丢失换行符，
#   所有代码被挤在一行内。
#   通过语法特征（如 ): 后跟 def、: 后跟 return 等）来恢复换行。
# ============================================================

def _fix_python_linebreaks(code):
    """
    修复 Python 代码块中丢失的换行符。
    策略：先用 %%NL%% 保护已有换行，然后通过正则匹配各种语法特征来插入换行。

    支持的换行模式：
    - ): 后跟 def/class/@ → 换行（新函数/类定义前）
    - ): 后跟 return/self./print/#/raise/pass → 换行 + 缩进（函数体内部）
    - : 后跟 def/class/for/while/if/try/with → 换行（新语句块前）
    - : 后跟 return/self./print/#/raise/pass → 换行 + 缩进（语句块体内部）
    - ) 后跟 for/while/if/try/def/class/@ → 换行（函数调用后新语句前）
    - return 后跟 self./print/raise → 换行
    - # 注释前 → 换行
    - 中文后跟 class/def → 换行（中文说明后跟代码定义）
    - 连续 class/def 定义之间 → 换行
    """
    code = code.replace('\r\n', '\n').replace('\r', '\n')
    # 统一特殊空白字符（如不间断空格、全角空格等）为普通空格
    code = re.sub(r'[\u00a0\u3000\u2000-\u200f\u2028-\u202f]+', ' ', code)
    # 用 %%NL%% 占位符保护已有换行，避免后续正则替换破坏它们
    code = code.replace('\n', ' %%NL%% ')

    # 1. ): 后跟 def/class/@ → 换行（新定义前，无缩进）
    code = re.sub(r'(\):)\s+(def\s+)', r'):\n\2', code)
    code = re.sub(r'(\):)\s+(class\s+)', r'):\n\2', code)
    code = re.sub(r'(\):)\s+(@)', r'):\n\2', code)

    # 2. 普通 ) 后跟 def/class/@ → 换行（无缩进）
    # 与上一条的区别：这里匹配的是 ) 而不是 ): ，
    # 处理函数调用括号后直接跟新定义的情况
    code = re.sub(r'(\))\s+(def\s+)', r')\n\2', code)
    code = re.sub(r'(\))\s+(class\s+)', r')\n\2', code)
    code = re.sub(r'(\))\s+(@)', r')\n\2', code)

    # 3. ): 后跟 return/self./print/#/raise/pass → 换行 + 4 空格缩进
    # 这些是函数体内部的语句，需要在换行后添加缩进
    code = re.sub(r'(\):)\s+(return\s+)', r'):\n    \2', code)
    code = re.sub(r'(\):)\s+(self\.)', r'):\n    \2', code)
    code = re.sub(r'(\):)\s+(print)', r'):\n    \2', code)
    code = re.sub(r'(\):)\s+(#)', r'):\n    \2', code)
    code = re.sub(r'(\):)\s+(raise\s+)', r'):\n    \2', code)
    code = re.sub(r'(\):)\s+(pass)', r'):\n    \2', code)

    # 4. : 后跟 def/class/for/while/if/try/with → 换行（无缩进）
    # 处理 Python 语句块结束（:）后跟新定义的情况
    code = re.sub(r'(:\s+)(def\s+)', r':\n\2', code)
    code = re.sub(r'(:\s+)(class\s+)', r':\n\2', code)
    code = re.sub(r'(:\s+)(for\s+)', r':\n\2', code)
    code = re.sub(r'(:\s+)(while\s+)', r':\n\2', code)
    code = re.sub(r'(:\s+)(if\s+)', r':\n\2', code)
    code = re.sub(r'(:\s+)(try:)', r':\n\2', code)
    code = re.sub(r'(:\s+)(with\s+)', r':\n\2', code)

    # 5. : 后跟 return/self./print/#/raise/pass → 换行 + 缩进
    code = re.sub(r'(:\s+)(return\s+)', r':\n    \2', code)
    code = re.sub(r'(:\s+)(self\.)', r':\n    \2', code)
    code = re.sub(r'(:\s+)(print)', r':\n    \2', code)
    code = re.sub(r'(:\s+)(#)', r':\n    \2', code)
    code = re.sub(r'(:\s+)(raise\s+)', r':\n    \2', code)
    code = re.sub(r'(:\s+)(pass)', r':\n    \2', code)

    # 6. ) 后跟 for/while/if/try/def/class/@ → 换行
    # 处理函数调用后直接跟新的控制流语句
    code = re.sub(r'(\))\s+(for\s+)', r')\n\2', code)
    code = re.sub(r'(\))\s+(while\s+)', r')\n\2', code)
    code = re.sub(r'(\))\s+(if\s+)', r')\n\2', code)
    code = re.sub(r'(\))\s+(try:)', r')\n\2', code)
    code = re.sub(r'(\))\s+(def\s+)', r')\n\2', code)
    code = re.sub(r'(\))\s+(class\s+)', r')\n\2', code)
    code = re.sub(r'(\))\s+(@)', r')\n\2', code)
    # 特殊情况：) 直接跟 class（没有空格）
    code = re.sub(r'(\))class\s+', r')\nclass ', code)

    # 7. return 语句后跟 self./print/raise → 换行
    # 处理 return 语句后直接跟新语句的情况
    code = re.sub(r'(return\s+[^#\n]+?)\s+(self\.)', r'\1\n\2', code)
    code = re.sub(r'(return\s+[^#\n]+?)\s+(print)', r'\1\n\2', code)
    code = re.sub(r'(return\s+[^#\n]+?)\s+(raise)', r'\1\n\2', code)

    # 8. # 注释前换行
    code = re.sub(r'([^\s])\s+#', r'\1\n#', code)
    code = re.sub(r'([\)\w\'\"])\s*#', r'\1\n#', code)

    # 9. 中文后跟 class/def → 换行
    # 处理中文说明后直接跟代码定义的情况
    code = re.sub(r'([\u4e00-\u9fff])(class\s+)', r'\1\n\2', code)
    code = re.sub(r'([\u4e00-\u9fff])(def\s+)', r'\1\n\2', code)

    # 10. 连续 class/def 定义之间换行
    code = re.sub(r'([\'\"])\s+class\s+', r'\1\nclass ', code)
    code = re.sub(r'([\'\"])\s+def\s+', r'\1\ndef ', code)

    # 恢复 %%NL%% 占位符为真正的换行符
    code = code.replace(' %%NL%% ', '\n')
    code = code.replace('%%NL%%', '\n')
    code = re.sub(r'\n{3,}', '\n\n', code)

    # 11. 最后一轮：逐行处理仍然残留在同一行内的代码段
    # 有时第一轮替换后，缩进代码仍然在行尾，需要再次拆分
    lines = []
    for line in code.split('\n'):
        if '"""' in line:
            lines.append(line)
            continue
        # 在 ): 后跟缩进代码时换行
        line = re.sub(r'(\):)\s{4,}([a-z_])', r'):\n\2', line)
        line = re.sub(r'(\))\s{4,}(def\s+)', r')\n\2', line)
        line = re.sub(r'(\))\s{4,}(class\s+)', r')\n\2', line)
        line = re.sub(r'(\))\s{4,}(@)', r')\n\2', line)
        # : 后跟缩进 return/self./print
        line = re.sub(r'(:\s{4,})(return\s+)', r':\n    \2', line)
        line = re.sub(r'(:\s{4,})(self\.)', r':\n    \2', line)
        line = re.sub(r'(:\s{4,})(print)', r':\n    \2', line)
        # 中文后跟 class/def
        line = re.sub(r'([\u4e00-\u9fff])(class\s+)', r'\1\n\2', line)
        line = re.sub(r'([\u4e00-\u9fff])(def\s+)', r'\1\n\2', line)
        lines.append(line)

    code = '\n'.join(lines)
    code = re.sub(r'\n{3,}', '\n\n', code)
    return code.strip()


def _fix_javascript_linebreaks(code):
    """
    修复 JavaScript 代码块中丢失的换行符。
    策略与 Python 修复类似，但使用 JavaScript 语法特征：
    - } 后换行（大括号闭合）
    - ; 后换行（语句结束）
    - function/var/let/const 前换行
    - if/for/while 前换行
    """
    code = code.replace('\r\n', '\n').replace('\r', '\n')
    code = code.replace('\n', ' %%NL%% ')

    # } 后换行（闭合大括号后换行）
    code = re.sub(r'(\})\s+', r'}\n', code)
    code = re.sub(r'(\})(\w)', r'}\n\2', code)
    # ; 后换行（语句分隔符后换行）
    code = re.sub(r'(;)\s+', r';\n', code)
    # function/var/let/const 前换行（新声明前）
    code = re.sub(r'([^\n])\s+(function\s+)', r'\1\n\2', code)
    code = re.sub(r'([^\n])\s+(var\s+)', r'\1\n\2', code)
    code = re.sub(r'([^\n])\s+(let\s+)', r'\1\n\2', code)
    code = re.sub(r'([^\n])\s+(const\s+)', r'\1\n\2', code)
    # if/for/while 前换行（控制流语句前）
    code = re.sub(r'([^\n])\s+(if\s*\()', r'\1\n\2', code)
    code = re.sub(r'([^\n])\s+(for\s*\()', r'\1\n\2', code)
    code = re.sub(r'([^\n])\s+(while\s*\()', r'\1\n\2', code)

    code = code.replace(' %%NL%% ', '\n')
    code = code.replace('%%NL%%', '\n')
    code = re.sub(r'\n{3,}', '\n\n', code)
    return code.strip()


def _fix_linebreaks_in_blocks(content):
    """
    修复代码块内部的换行，并自动修正语言标签。
    遍历所有 ``` 代码块，根据语言类型调用对应的修复函数。
    同时利用 _detect_language() 重新检测语言，修正错误标签。
    例如：原本标记为 javascript 的 Tornado 代码会被修正为 python。
    """
    def fix_block(match):
        lang = match.group(1) or ''
        code = match.group(2)
        # 短代码（< 20 字符）不需要换行修复
        if not code or len(code) < 20:
            return f'```{lang}\n{code}\n```'

        # 重新检测语言，修正错误标签
        actual_lang = _detect_language(code)
        if actual_lang:
            lang = actual_lang

        # 根据语言类型选择修复策略
        if lang == 'python':
            fixed = _fix_python_linebreaks(code)
        elif lang == 'javascript':
            fixed = _fix_javascript_linebreaks(code)
        elif lang == 'bash':
            # shell 命令通常已有正确换行，只需清理空白
            fixed = code.strip()
        else:
            # 不确定时先尝试 Python 修复，如果无效再尝试 JS 修复
            fixed = _fix_python_linebreaks(code)
            if '\n' not in fixed.strip():
                fixed = _fix_javascript_linebreaks(code)

        return f'```{lang}\n{fixed}\n```'

    return re.sub(r'```(\w*)\n(.*?)\n```', fix_block, content, flags=re.DOTALL)


# ============================================================
# 公开 API
# ============================================================
def fix_markdown(content):
    """
    修复 Markdown 内容中的代码块格式。
    执行两个阶段：
    1. _add_code_blocks() — 为未包裹的代码添加 ``` 标记
    2. _fix_linebreaks_in_blocks() — 修复代码块内部的换行

    参数：
        content: 原始 Markdown 文本字符串

    返回：
        修复后的 Markdown 文本字符串
    """
    content = _add_code_blocks(content)
    content = _fix_linebreaks_in_blocks(content)
    return content


def fix_markdown_file(filepath):
    """读取文件，修复后写回"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    fixed = fix_markdown(content)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(fixed)
    blocks = re.findall(r'^```(\w*)', fixed, re.MULTILINE)
    print(f"文件已处理: {filepath}")
    print(f"代码块总数: {len(blocks)}")
    for b in sorted(set(blocks)):
        print(f"  ```{b}: {blocks.count(b)}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        fix_markdown_file(sys.argv[1])
    else:
        print("用法: python scripts/fix_code_format.py <markdown文件路径>")