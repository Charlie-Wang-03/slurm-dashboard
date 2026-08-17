"""i18n tests: language detection and dictionary integrity."""

from app.i18n import LANG_COOKIE, LANG_EN, LANG_ZH, STRINGS, detect_language, get_strings


class FakeRequest:
    def __init__(self, accept_language: str = "", cookies: dict | None = None):
        self.headers = {"accept-language": accept_language}
        self.cookies = cookies or {}


class TestDetectLanguage:
    def test_cookie_wins_over_config(self):
        req = FakeRequest("en-US", {LANG_COOKIE: "zh"})
        assert detect_language(req, "en") == LANG_ZH
        req = FakeRequest("zh-CN", {LANG_COOKIE: "en"})
        assert detect_language(req, "zh") == LANG_EN

    def test_cookie_wins_over_browser_header(self):
        assert detect_language(FakeRequest("zh-CN", {LANG_COOKIE: "en"})) == LANG_EN
        assert detect_language(FakeRequest("en-US", {LANG_COOKIE: "zh"})) == LANG_ZH

    def test_invalid_cookie_falls_back(self):
        # A stale/foreign cookie value must not crash or stick.
        req = FakeRequest("zh-CN", {LANG_COOKIE: "fr"})
        assert detect_language(req) == LANG_ZH
        assert detect_language(req, "en") == LANG_EN

    def test_ui_lang_config_wins(self):
        assert detect_language(FakeRequest("en-US"), "zh") == LANG_ZH
        assert detect_language(FakeRequest("zh-CN"), "en") == LANG_EN

    def test_browser_zh_matches(self):
        assert detect_language(FakeRequest("zh-CN,zh;q=0.9,en;q=0.8")) == LANG_ZH
        assert detect_language(FakeRequest("zh;q=0.9")) == LANG_ZH

    def test_default_english(self):
        assert detect_language(FakeRequest("")) == LANG_EN
        assert detect_language(FakeRequest("en-US,en;q=0.9")) == LANG_EN
        assert detect_language(FakeRequest("fr-FR,fr;q=0.9")) == LANG_EN


class TestStrings:
    def test_zh_has_same_keys_as_en(self):
        assert set(STRINGS[LANG_EN].keys()) == set(STRINGS[LANG_ZH].keys())

    def test_get_strings_fallback(self):
        assert get_strings("fr") is STRINGS[LANG_EN]
        assert get_strings(LANG_ZH) is STRINGS[LANG_ZH]

    def test_placeholder_key_present(self):
        assert "submit.placeholder" in STRINGS[LANG_EN]
