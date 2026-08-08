from app.services.bot_signals import is_bot_suspect, score_bot


def test_generic_compatible_ua_is_bot():
    score, reasons = score_bot("Mozilla/5.0 (compatible)")
    assert score >= 80
    assert is_bot_suspect(score)
    assert "generic_ua" in reasons or "compatible_ua" in reasons


def test_real_safari_is_clean():
    score, reasons = score_bot(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15"
    )
    assert score < 50
    assert not is_bot_suspect(score)
    assert reasons == []


def test_crawl_keyword():
    score, reasons = score_bot("Googlebot/2.1 (+http://www.google.com/bot.html)")
    assert score >= 70
    assert "ua_keyword" in reasons
