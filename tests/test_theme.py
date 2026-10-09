from gui.theme import DARK, LIGHT


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_tokens_meet_wcag_aa_in_both_themes():
    pairs = [(fg, bg) for fg in ("text", "text2", "text3") for bg in ("bg", "surface")]
    pairs += [("text", "surface2"), ("text2", "surface2"), ("text", "selection"), ("on_accent", "accent"), ("surface", "warning")]
    pairs += [(tone, bg) for tone in ("info", "warning", "danger", "success") for bg in ("bg", "surface")]
    for name, palette in (("light", LIGHT), ("dark", DARK)):
        for fg, bg in pairs:
            assert contrast(palette[fg], palette[bg]) >= 4.5, (name, fg, bg, round(contrast(palette[fg], palette[bg]), 2))
