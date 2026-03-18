from tg_agent_framework.bot.markdown import TG_MAX_LENGTH, truncate_for_telegram


def test_truncate_for_telegram_keeps_short_text_unchanged():
    text = "<b>ok</b>"

    assert truncate_for_telegram(text) == text


def test_truncate_for_telegram_strips_html_before_truncating_long_messages():
    long_html = "<b>状态</b>\n<pre>" + ("日志内容\n" * 1000) + "</pre>"

    result = truncate_for_telegram(long_html)

    assert len(result) <= TG_MAX_LENGTH
    assert "⚠️ 消息过长已截断..." in result
    assert "<b>" not in result
    assert "<pre>" not in result
    assert result.startswith("状态")
