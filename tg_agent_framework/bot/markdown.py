"""
Markdown → Telegram HTML 安全转换

处理大模型输出的 Markdown 格式，转为 Telegram 支持的受限 HTML。
"""

from __future__ import annotations

import html as _html
import re

# Telegram 单条消息最大长度
TG_MAX_LENGTH = 4096
# 原始文本预截断阈值（留足 HTML 标签膨胀空间）
TG_RAW_LIMIT = 3500


def truncate_for_telegram(text: str) -> str:
    """截断过长的消息，确保不超过 Telegram 限制"""
    if len(text) <= TG_MAX_LENGTH:
        return text
    if re.search(r"<[^>]+>", text):
        text = strip_html_tags(text)
    return text[: TG_MAX_LENGTH - 50] + "\n\n⚠️ 消息过长已截断..."


def strip_html_tags(text: str) -> str:
    """移除所有 HTML 标签，回退为纯文本"""
    return re.sub(r"<[^>]+>", "", text)


def markdown_to_telegram_html(text: str) -> str:
    """
    将大模型的标准 Markdown 转换为 Telegram 支持的安全 HTML。
    内部会先预截断原始文本，转换后再做二次安全截断。
    """
    if not text:
        return ""

    # ── 第一步: 预截断原始文本 ──
    if len(text) > TG_RAW_LIMIT:
        text = text[:TG_RAW_LIMIT] + "\n\n⚠️ 消息过长已截断..."

    # ── 第二步: Markdown → HTML 转换 ──
    blocks: list[str] = []

    def placeholder_code_block(match):
        code = match.group(2)
        safe_code = _html.escape(code)
        blocks.append(f"<pre><code>{safe_code}</code></pre>")
        return f"___CODE_BLOCK_{len(blocks) - 1}___"

    text = re.sub(r"```(\w*)\n(.*?)```", placeholder_code_block, text, flags=re.DOTALL)

    # 转义剩余文本中的 HTML 特殊符号
    text = _html.escape(text)

    # 行内代码
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    # 加粗
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    # 斜体
    text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    # 标题
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 还原代码块
    for i, block in enumerate(blocks):
        text = text.replace(f"___CODE_BLOCK_{i}___", block)

    # ── 第三步: 最终安全兜底 ──
    if len(text) > TG_MAX_LENGTH:
        text = strip_html_tags(text)
        if len(text) > TG_MAX_LENGTH:
            text = text[: TG_MAX_LENGTH - 50] + "\n\n⚠️ 消息过长已截断..."

    return text
