"""Generated HTML extraction and boundary cleanup."""

import logging
import re

from aetherviz_service.aetherviz.limits import MIN_MODEL_HTML_CHARS

logger = logging.getLogger(__name__)


class AetherVizInteractiveHtmlError(ValueError):
    pass


AI_ATTRIBUTION_PATTERN = re.compile(
    r"(?:[—\-·•]\s*)?由\s*宾果AI\s*(?:为你)?生成\s*(?:❤️|❤|\ufe0f)?",
    re.IGNORECASE,
)


def sanitize_aetherviz_html(html: str) -> str:
    cleaned = (html or "").strip()
    return AI_ATTRIBUTION_PATTERN.sub("", cleaned)


def _balance_js_brackets(script_chunk: str) -> str:
    """使用词法扫描状态机分析截断的 JavaScript 代码块，返回为使其无语法错误而必须追加的闭合字符后缀。

    支持正确闭合：
    - 单行/多行注释 (//, /* */)
    - 单引号、双引号、反引号模板字符串 (', ", `)
    - 模板字符串内部的 ${...} JS 表达式插值
    - 外层及内部未闭合的大括号 {}
    """
    in_single_quote = False
    in_double_quote = False
    in_template_literal = False
    in_line_comment = False
    in_block_comment = False

    braces_stack = []

    i = 0
    n = len(script_chunk)
    while i < n:
        char = script_chunk[i]

        # 处理转义字符
        if char == "\\" and (in_single_quote or in_double_quote or in_template_literal):
            i += 2
            continue

        # 处理单行注释
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            i += 1
            continue

        # 处理多行注释
        if in_block_comment:
            if char == "*" and i + 1 < n and script_chunk[i + 1] == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        # 处理单引号字符串
        if in_single_quote:
            if char == "'":
                in_single_quote = False
            i += 1
            continue

        # 处理双引号字符串
        if in_double_quote:
            if char == '"':
                in_double_quote = False
            i += 1
            continue

        # 处理模板字面量 (反引号)
        if in_template_literal:
            # 检查模板字符串内的 JS 表达式插值 ${
            if char == "$" and i + 1 < n and script_chunk[i + 1] == "{":
                braces_stack.append("${")
                in_template_literal = False
                i += 2
                continue
            elif char == "`":
                in_template_literal = False
            i += 1
            continue

        # 普通 JS 代码区域
        # 检查注释开头
        if char == "/" and i + 1 < n:
            if script_chunk[i + 1] == "/":
                in_line_comment = True
                i += 2
                continue
            elif script_chunk[i + 1] == "*":
                in_block_comment = True
                i += 2
                continue

        # 检查字符串开头
        if char == "'":
            in_single_quote = True
            i += 1
            continue
        elif char == '"':
            in_double_quote = True
            i += 1
            continue
        elif char == "`":
            in_template_literal = True
            i += 1
            continue

        # 检查大括号
        if char == "{":
            braces_stack.append("{")
        elif char == "}":
            if braces_stack:
                top = braces_stack.pop()
                if top == "${":
                    in_template_literal = True

        i += 1

    suffix = ""
    # 1. 首先闭合当前字符串或注释状态
    if in_block_comment:
        suffix += "*/"
    elif in_template_literal:
        suffix += "`"
    elif in_single_quote:
        suffix += "'"
    elif in_double_quote:
        suffix += '"'

    # 2. 闭合大括号或 ${} 嵌套
    while braces_stack:
        top = braces_stack.pop()
        if top == "${":
            suffix += "}`"  # 先闭合表达式，再闭合外层反引号模板字符串
        else:
            suffix += "}"

    return suffix


def parse_interactive_html(raw_output: str) -> str:
    """从 LLM 输出中提取并验证自包含的交互式 HTML，并支持对截断内容的自动智能闭合。

    该函数负责以下工作：
    1. 去除 LLM 输出中可能包含的 Markdown 代码围栏（```html...```）
    2. 提取以 <!DOCTYPE html> 或 <html> 开头的 HTML 内容
    3. 如果存在 </html> 结束标签，精确截取完整 HTML
    4. 基本校验：确保包含 HTML 基础标记
    5. 智能补全：检测截断情况并自动闭合缺失的标签：
       - 如果 <script> 未闭合，使用词法状态机智能闭合未完成的括号/字符串/注释，
         不在此处判定失败，交由后续的确定性校验与模型修复通道处理语义完整性
       - 如果 <style> 未闭合，自动添加 </style>
       - 自动添加缺失的 </body> 和 </html>
    6. 长度校验：确保生成的 HTML 内容足够完整（至少 150 字符）

    参数:
        raw_output: LLM 原始输出字符串，可能包含 Markdown 围栏或截断内容

    返回:
        清理后的完整 HTML 字符串

    异常:
        AetherVizInteractiveHtmlError: 当输出为空、缺少 HTML 标记或内容过短时抛出
    """
    if not raw_output:
        raise AetherVizInteractiveHtmlError("LLM 输出为空")

    # 去除 Markdown 代码围栏
    stripped = _strip_code_fences(raw_output).strip()

    # 如果有多个围栏或者残留的前后文，进行一些合理清洗
    # 提取 HTML 首尾
    if "<!DOCTYPE" in stripped.upper():
        start_idx = stripped.upper().find("<!DOCTYPE")
        stripped = stripped[start_idx:]
    elif "<HTML" in stripped.upper():
        start_idx = stripped.upper().find("<HTML")
        stripped = stripped[start_idx:]

    # 如果发现了 </html>，进行精确截取
    if "</HTML>" in stripped.upper():
        end_idx = stripped.upper().rfind("</HTML>")
        stripped = stripped[: end_idx + 7]

    # 基本合规性校验
    lower_content = stripped.lower()
    if not ("<!doctype html" in lower_content or "<html" in lower_content):
        raise AetherVizInteractiveHtmlError("生成的页面缺少 HTML 基础标记")

    # ─── 终极容错：智能补全闭合标签（防截断） ───
    if "</html" not in lower_content:
        logger.warning("AetherViz: 检测到大模型输出可能被截断，缺少 </html> 闭合标签，启动智能缝合补齐...")

        # 1. 检查是否在 script 块内截断了 (即含有 <script 但在它之后没有 </script>)
        #    不再直接判失败：用词法状态机计算需要补齐的闭合字符，缝合后交由
        #    后续 JS 语法校验 + widget 契约校验决定是否需要走一次模型修复。
        last_script_open = lower_content.rfind("<script")
        last_script_close = lower_content.rfind("</script")
        if last_script_open > last_script_close:
            tag_end = stripped.find(">", last_script_open)
            content_start = tag_end + 1 if tag_end != -1 else last_script_open + len("<script")
            script_body = stripped[content_start:]
            closing_suffix = _balance_js_brackets(script_body)
            stripped = stripped[:content_start] + script_body + closing_suffix + "\n</script>"
            logger.info("AetherViz: 智能闭合了被截断的 <script> 内容，交由后续校验/修复处理语义完整性")
            lower_content = stripped.lower()

        # 2. 检查是否在 style 块内截断了
        last_style_open = lower_content.rfind("<style")
        last_style_close = lower_content.rfind("</style")
        if last_style_open > last_style_close:
            stripped += "\n</style>"
            logger.info("AetherViz: 自动闭合了未结束的 <style> 标签")

        # 3. 检查并闭合 body 和 html
        lower_content = stripped.lower()
        if "</body>" not in lower_content:
            stripped += "\n</body>"
        stripped += "\n</html>"
        logger.info("AetherViz: 自动缝合补齐了 </body></html> 标签，页面加载成功。")

    # 再次做最终字符长度检验
    if len(stripped) < MIN_MODEL_HTML_CHARS:
        raise AetherVizInteractiveHtmlError(
            f"生成的 HTML 内容过短（当前仅 {len(stripped)} 字符），不符合完整交互页面要求"
        )

    return stripped


def _strip_code_fences(text: str) -> str:
    """去除 LLM 输出中可能包含的 Markdown 代码围栏（```html...```）。"""
    stripped = text.strip()
    fenced = re.fullmatch(r"```[a-zA-Z0-9_-]*\s*(.*?)\s*```", stripped, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    # 只去掉开头和结尾的围栏标记，不破坏正文中可能存在的模板字面量反引号
    stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()
