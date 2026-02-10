# tests/unit/test_content_cleaner.py
"""
Unit tests for content cleaner utilities.

Covers:
- Each pattern category (CTA, newsletter, social, cookie, related, ad, author bio, video)
- Paragraph-context guard (only entire lines stripped)
- Attribution whitelist
- Quotation guard
- No-op on clean text
- Feature flag off
- Whitespace normalization
"""

from unittest.mock import patch

from app.utils.content_cleaner import clean_article_body


class TestCleanArticleBody:
    """Core cleaning tests."""

    def test_returns_empty_for_none(self):
        assert clean_article_body(None) == ""

    def test_returns_empty_for_empty(self):
        assert clean_article_body("") == ""

    def test_no_op_on_clean_text(self):
        text = "The president met with foreign leaders today to discuss trade agreements.\n\nNegotiations are expected to continue through the week."
        assert clean_article_body(text) == text

    def test_preserves_normal_article(self):
        text = (
            "WASHINGTON — The Senate voted 52-48 on Tuesday to approve the new spending bill.\n\n"
            "Senator Jane Smith said the measure was necessary to address the growing deficit.\n\n"
            '"We cannot continue to kick the can down the road," Smith told reporters.'
        )
        assert clean_article_body(text) == text


class TestCTAPatterns:
    """Category 1: CTA/navigation removal."""

    def test_removes_read_more(self):
        text = "Article content here.\n\nRead more"
        result = clean_article_body(text)
        assert "Read more" not in result
        assert "Article content here." in result

    def test_removes_read_full_story(self):
        text = "Article content.\n\nRead the full story."
        result = clean_article_body(text)
        assert "Read the full story" not in result

    def test_removes_click_here(self):
        text = "Article content.\n\nClick here"
        result = clean_article_body(text)
        assert "Click here" not in result

    def test_removes_watch_now(self):
        text = "Content.\n\nWatch now"
        result = clean_article_body(text)
        assert "Watch now" not in result

    def test_removes_subscribe_now(self):
        text = "Content.\n\nSubscribe now"
        result = clean_article_body(text)
        assert "Subscribe now" not in result

    def test_removes_continue_reading(self):
        text = "Content.\n\nContinue reading"
        result = clean_article_body(text)
        assert "Continue reading" not in result

    def test_removes_download_app(self):
        text = "Content.\n\nDownload the app"
        result = clean_article_body(text)
        assert "Download the app" not in result


class TestNewsletterPatterns:
    """Category 2: Newsletter/subscription removal."""

    def test_removes_sign_up_for(self):
        text = "Article.\n\nSign up for our daily newsletter"
        result = clean_article_body(text)
        assert "Sign up" not in result

    def test_removes_get_our_newsletter(self):
        text = "Article.\n\nGet our newsletter."
        result = clean_article_body(text)
        assert "newsletter" not in result

    def test_removes_enter_email(self):
        text = "Article.\n\nEnter your email to stay updated"
        result = clean_article_body(text)
        assert "Enter your email" not in result

    def test_removes_get_morning_newsletter(self):
        text = "Article.\n\nGet the morning newsletter delivered to your inbox"
        result = clean_article_body(text)
        assert "morning newsletter" not in result


class TestSocialPatterns:
    """Category 3: Social/sharing removal."""

    def test_removes_share_on_facebook(self):
        text = "Article.\n\nShare on Facebook"
        result = clean_article_body(text)
        assert "Share on Facebook" not in result

    def test_removes_follow_us(self):
        text = "Article.\n\nFollow us on Twitter."
        result = clean_article_body(text)
        assert "Follow us" not in result

    def test_removes_tweet_this(self):
        text = "Article.\n\nTweet this"
        result = clean_article_body(text)
        assert "Tweet this" not in result

    def test_removes_share_via(self):
        text = "Article.\n\nShare this via email."
        result = clean_article_body(text)
        assert "Share this via" not in result


class TestCookiePatterns:
    """Category 4: Cookie/GDPR removal."""

    def test_removes_we_use_cookies(self):
        text = "Article.\n\nWe use cookies to improve your experience"
        result = clean_article_body(text)
        assert "cookies" not in result

    def test_removes_accept_all_cookies(self):
        text = "Article.\n\nAccept all cookies"
        result = clean_article_body(text)
        assert "cookies" not in result

    def test_removes_site_uses_cookies(self):
        text = "Article.\n\nThis site uses cookies to enhance functionality"
        result = clean_article_body(text)
        assert "cookies" not in result


class TestRelatedPatterns:
    """Category 5: Related content removal."""

    def test_removes_you_might_also_like(self):
        text = "Article.\n\nYou might also like:"
        result = clean_article_body(text)
        assert "You might also like" not in result

    def test_removes_related_stories(self):
        text = "Article.\n\nRelated stories:"
        result = clean_article_body(text)
        assert "Related stories" not in result

    def test_removes_recommended(self):
        text = "Article.\n\nRecommended for you:"
        result = clean_article_body(text)
        assert "Recommended for you" not in result

    def test_removes_trending(self):
        text = "Article.\n\nTrending now:"
        result = clean_article_body(text)
        assert "Trending now" not in result

    def test_removes_most_read(self):
        text = "Article.\n\nMost read:"
        result = clean_article_body(text)
        assert "Most read" not in result


class TestAdPatterns:
    """Category 6: Ad marker removal."""

    def test_removes_advertisement(self):
        text = "Article.\n\nAdvertisement\n\nMore content."
        result = clean_article_body(text)
        assert "Advertisement" not in result
        assert "More content." in result

    def test_removes_sponsored_content(self):
        text = "Article.\n\nSponsored content"
        result = clean_article_body(text)
        assert "Sponsored content" not in result

    def test_removes_paid_content(self):
        text = "Article.\n\nPaid content"
        result = clean_article_body(text)
        assert "Paid content" not in result


class TestAuthorBioPatterns:
    """Category 7: Author bio CTA removal."""

    def test_removes_follow_handle(self):
        text = "Article.\n\nFollow @journalist"
        result = clean_article_body(text)
        assert "@journalist" not in result

    def test_removes_bare_handle(self):
        text = "Article.\n\n@journalist_name"
        result = clean_article_body(text)
        assert "@journalist_name" not in result

    def test_removes_follow_on_twitter(self):
        text = "Article.\n\nFollow Sarah on Twitter"
        result = clean_article_body(text)
        assert "Follow Sarah on Twitter" not in result


class TestVideoTransform:
    """Category 8: Video/embed transformation."""

    def test_transforms_video_reference(self):
        text = "Article.\n\n[Video: Climate summit speech]\n\nMore content."
        result = clean_article_body(text)
        assert "[This article includes multimedia content at the original source.]" in result
        assert "Climate summit speech" not in result
        assert "More content." in result

    def test_transforms_watch_video(self):
        text = "Article.\n\nWatch the video below."
        result = clean_article_body(text)
        assert "[This article includes multimedia content at the original source.]" in result

    def test_transforms_play_video(self):
        text = "Article.\n\nPlay video"
        result = clean_article_body(text)
        assert "[This article includes multimedia content at the original source.]" in result

    def test_transforms_embed_reference(self):
        text = "Article.\n\n[Embed: Twitter post]\n\nMore content."
        result = clean_article_body(text)
        assert "[This article includes multimedia content at the original source.]" in result


class TestParagraphContextGuard:
    """Only strip ENTIRE lines, not phrases within sentences."""

    def test_preserves_read_more_in_sentence(self):
        text = "The company told users to read more about the policy changes on its website."
        assert clean_article_body(text) == text

    def test_preserves_subscribe_in_sentence(self):
        text = "Analysts recommend users subscribe to the premium plan for full access."
        assert clean_article_body(text) == text

    def test_preserves_watch_now_in_sentence(self):
        text = 'The company\'s "Watch Now" button was redesigned for better accessibility.'
        assert clean_article_body(text) == text

    def test_preserves_cookies_in_sentence(self):
        text = "The EU's regulation on cookies and digital advertising will take effect next year."
        assert clean_article_body(text) == text

    def test_preserves_newsletter_in_sentence(self):
        text = "The Times launched a new newsletter covering technology and AI developments."
        assert clean_article_body(text) == text

    def test_preserves_advertisement_in_sentence(self):
        text = "The advertisement spending across digital platforms increased by 15% in Q3."
        assert clean_article_body(text) == text

    def test_preserves_follow_in_sentence(self):
        text = "Officials urged citizens to follow the new guidelines closely."
        assert clean_article_body(text) == text


class TestAttributionWhitelist:
    """Never strip lines containing journalistic attribution."""

    def test_preserves_according_to(self):
        text = "Sign up for our daily updates, according to the company spokesperson."
        assert clean_article_body(text) == text

    def test_preserves_as_reported_by(self):
        text = "Get our newsletter, as reported by multiple sources."
        assert clean_article_body(text) == text

    def test_preserves_contributed_to_this_report(self):
        text = "John Smith contributed to this report"
        assert clean_article_body(text) == text

    def test_preserves_spoke_on_condition(self):
        text = "The official spoke on condition of anonymity."
        assert clean_article_body(text) == text

    def test_preserves_told_reporters(self):
        text = "She told reporters at the press conference."
        assert clean_article_body(text) == text

    def test_preserves_reporting_by(self):
        text = "Reporting by Jane Doe; editing by John Smith"
        assert clean_article_body(text) == text


class TestQuotationGuard:
    """Never strip text inside quotation marks."""

    def test_preserves_quoted_sign_up(self):
        text = '"Sign up for our newsletter" is what the CEO told shareholders.'
        assert clean_article_body(text) == text

    def test_preserves_curly_quoted_read_more(self):
        text = "\u201cRead more\u201d was the only instruction given."
        assert clean_article_body(text) == text

    def test_preserves_single_quoted(self):
        text = "'Subscribe now' appeared on every page of the site."
        assert clean_article_body(text) == text


class TestFeatureFlag:
    """Feature flag off should return text unchanged."""

    @patch.dict("os.environ", {"CONTENT_CLEANING_ENABLED": "false"})
    def test_disabled_returns_original(self):
        text = "Article.\n\nRead more\n\nSubscribe now"
        assert clean_article_body(text) == text

    @patch.dict("os.environ", {"CONTENT_CLEANING_ENABLED": "0"})
    def test_disabled_zero_returns_original(self):
        text = "Article.\n\nRead more"
        assert clean_article_body(text) == text

    @patch.dict("os.environ", {"CONTENT_CLEANING_ENABLED": "true"})
    def test_enabled_cleans(self):
        text = "Article.\n\nRead more"
        result = clean_article_body(text)
        assert "Read more" not in result


class TestWhitespaceNormalization:
    """Collapse multiple blank lines after removing artifacts."""

    def test_collapses_triple_blank_lines(self):
        text = "Paragraph 1.\n\nRead more\n\n\n\nParagraph 2."
        result = clean_article_body(text)
        assert "\n\n\n" not in result
        assert "Paragraph 1." in result
        assert "Paragraph 2." in result

    def test_strips_leading_trailing_whitespace(self):
        text = "\n\nRead more\n\nArticle content.\n\nSubscribe now\n\n"
        result = clean_article_body(text)
        assert not result.startswith("\n")
        assert not result.endswith("\n")
        assert "Article content." in result


class TestMultipleArtifacts:
    """Test removal of multiple artifact types in one body."""

    def test_removes_multiple_artifact_types(self):
        text = (
            "The Senate approved the bill on Tuesday.\n\n"
            "Senator Smith called it a historic moment.\n\n"
            "Advertisement\n\n"
            "The vote was 52-48 along party lines.\n\n"
            "Related stories:\n\n"
            "Sign up for our daily newsletter\n\n"
            "Share on Facebook\n\n"
            "Follow @reporter"
        )
        result = clean_article_body(text)
        assert "The Senate approved" in result
        assert "Senator Smith" in result
        assert "The vote was" in result
        assert "Advertisement" not in result
        assert "Related stories" not in result
        assert "Sign up" not in result
        assert "Share on Facebook" not in result
        assert "@reporter" not in result
