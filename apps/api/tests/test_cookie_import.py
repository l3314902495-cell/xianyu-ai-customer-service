from app.api.accounts import _parse_cookie_text


def test_parse_cookie_header() -> None:
    cookies = _parse_cookie_text(
        "Cookie: unb=123; cookie2=abc; _m_h5_tk=token_1; tracknick=test"
    )

    assert cookies["unb"] == "123"
    assert cookies["cookie2"] == "abc"
    assert cookies["_m_h5_tk"] == "token_1"
    assert cookies["tracknick"] == "test"
