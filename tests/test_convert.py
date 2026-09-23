import pytest

from to_md.convert import convert_to_markdown, sanitize_markdown


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("สวัสดี\x00ครับ", "สวัสดีครับ"),
        ("\x00\x00\x00", ""),
        ("a\x01b\x08c\x0bd\x0ce\x1bf\x1fg", "abcdefg"),
        ("del\x7f c1\x85\x9f", "del c1"),
        ("line\r\nnext", "line\nnext"),
    ],
)
def test_sanitize_strips_control_characters(raw, expected):
    assert sanitize_markdown(raw) == expected


def test_sanitize_keeps_newlines_tabs_and_text():
    text = "# หัวข้อ\n\n| a\t| b |\n\n- ภาษาไทย ✓ émoji 🎉\n"
    assert sanitize_markdown(text) == text


def test_convert_to_markdown_strips_nul_from_output():
    source = "สวัสดี\x00ครับ\n\tok\x07\n".encode()
    markdown = convert_to_markdown(source, ".txt")
    assert "\x00" not in markdown
    assert "\x07" not in markdown
    assert "สวัสดีครับ" in markdown
    assert "\tok" in markdown
