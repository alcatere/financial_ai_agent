from src.notifications.telegram import TelegramNotifier, escape_markdown


def test_parse_confirm_with_underscore():
    assert TelegramNotifier._parse("/confirm_42") == (42, True)


def test_parse_confirm_with_space():
    assert TelegramNotifier._parse("/confirm 42") == (42, True)


def test_parse_reject():
    assert TelegramNotifier._parse("/reject_7") == (7, False)


def test_parse_unrelated_text_returns_none():
    assert TelegramNotifier._parse("hello there") is None


def test_parse_is_case_insensitive():
    assert TelegramNotifier._parse("/CONFIRM_3") == (3, True)


def test_escape_markdown_escapes_special_chars():
    assert escape_markdown("growth_rate is *strong*") == "growth\\_rate is \\*strong\\*"


def test_escape_markdown_leaves_plain_text_untouched():
    assert escape_markdown("strong earnings growth") == "strong earnings growth"


def test_escape_markdown_handles_backtick_and_bracket():
    assert escape_markdown("`code` and [link]") == "\\`code\\` and \\[link]"
