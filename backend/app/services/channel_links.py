from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse

from app.services.bio_parser import ParsedSocial, platform_for_url

logger = logging.getLogger(__name__)

_YT_INITIAL_DATA_RE = re.compile(
    r"ytInitialData\s*=\s*(\{.*?\});</script>",
    re.DOTALL,
)
_TME_RE = re.compile(r"(?i)\b(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)")


def fetch_channel_about_socials(channel_id: str) -> list[ParsedSocial]:
    """Pull social/website links from the channel About page.

    YouTube often stores Telegram/Instagram/etc. as About links, which are
    NOT included in Data API snippet.description.
    """
    if not channel_id:
        return []

    html = _fetch_about_html(channel_id)
    if not html:
        return []

    found: list[ParsedSocial] = []
    seen: set[tuple[str, str]] = set()

    def add(platform: str, value: str) -> None:
        cleaned = value.strip().rstrip(".,);]}")
        if not cleaned:
            return
        key = (platform, cleaned.lower())
        if key in seen:
            return
        seen.add(key)
        found.append(ParsedSocial(platform=platform, value=cleaned))

    for title, link in _links_from_yt_initial_data(html):
        url = _normalize_external_url(link)
        if not url:
            continue
        platform = platform_for_url(url)
        if platform == "website" and title:
            hinted = _platform_from_title(title)
            if hinted:
                platform = hinted
        add(platform, url)

    # Fallback: raw t.me occurrences in the page payload
    for match in _TME_RE.finditer(html):
        add("telegram", f"https://t.me/{match.group(1)}")

    return found


def _fetch_about_html(channel_id: str) -> str | None:
    url = f"https://www.youtube.com/channel/{channel_id}/about"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=context) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Failed to fetch About page for %s: %s", channel_id, exc)
        return None


def _links_from_yt_initial_data(html: str) -> list[tuple[str, str]]:
    match = _YT_INITIAL_DATA_RE.search(html)
    if not match:
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    links: list[tuple[str, str]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            view = node.get("channelExternalLinkViewModel")
            if isinstance(view, dict):
                title = _text_content(view.get("title"))
                link = _text_content(view.get("link"))
                if link:
                    links.append((title, link))
            primary = node.get("primaryLinks")
            if isinstance(primary, list):
                for item in primary:
                    if not isinstance(item, dict):
                        continue
                    title = _text_content((item.get("title") or {}).get("simpleText"))
                    if not title:
                        title = _text_content(item.get("title"))
                    endpoint = (
                        (item.get("navigationEndpoint") or {})
                        .get("urlEndpoint", {})
                        .get("url")
                    )
                    if endpoint:
                        links.append((title or "", endpoint))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return links


def _text_content(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if "content" in value and isinstance(value["content"], str):
            return value["content"].strip()
        if "simpleText" in value and isinstance(value["simpleText"], str):
            return value["simpleText"].strip()
    return str(value).strip()


def _normalize_external_url(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None

    if text.startswith("//"):
        text = "https:" + text

    # YouTube redirect wrapper
    if "youtube.com/redirect" in text:
        try:
            qs = parse_qs(urlparse(text).query)
            target = qs.get("q", [None])[0]
            if target:
                text = unquote(target)
        except Exception:
            pass

    if text.startswith("www."):
        text = "https://" + text
    if not re.match(r"(?i)^https?://", text):
        # bare t.me/foo etc.
        if re.match(r"(?i)^[a-z0-9.-]+\.[a-z]{2,}(/|$)", text):
            text = "https://" + text
        else:
            return None

    return text


def _platform_from_title(title: str) -> str | None:
    t = title.strip().lower()
    mapping = {
        "telegram": "telegram",
        "instagram": "instagram",
        "twitter": "twitter",
        "x": "twitter",
        "facebook": "facebook",
        "linkedin": "linkedin",
        "whatsapp": "whatsapp",
        "tiktok": "tiktok",
        "threads": "threads",
        "youtube": "youtube",
    }
    for key, platform in mapping.items():
        if key in t:
            return platform
    return None
