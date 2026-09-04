from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

# #region agent log
_DEBUG_LOG_PATH = "/Users/aditya.vaish/Desktop/kol-yt-search/kol-yt-search/.cursor/debug-6b9c45.log"


def _agent_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "sessionId": "6b9c45",
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass


# #endregion

from app.services.bio_parser import (
    ALLOWED_SOCIAL_PLATFORMS,
    ParsedSocial,
    normalize_platform,
    parse_bio,
    platform_for_url,
)

logger = logging.getLogger(__name__)

# Public WEB client key used by youtube.com (not a secret Data API key).
_INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_INNERTUBE_CLIENT_VERSION = "2.20250312.01.00"
_INNERTUBE_BROWSE_URL = (
    f"https://www.youtube.com/youtubei/v1/browse?key={_INNERTUBE_API_KEY}"
)

_YT_INITIAL_DATA_RE = re.compile(
    r"ytInitialData\s*=\s*(\{.*?\});</script>",
    re.DOTALL,
)
_TME_RE = re.compile(r"(?i)\b(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)")
_EMAIL_NOISE = re.compile(
    r"(?i)(google|youtube|sentry|gstatic|schema|example\.com|\.png|\.jpg|\.webp|wixpress)"
)
_BOT_WALL_RE = re.compile(
    r"(?i)(sorry.?i.?m not a robot|captcha|consent\.youtube|/sorry/index)"
)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_CONSENT_COOKIE = "SOCS=CAI; CONSENT=YES+cb.20210328-17-p0.en+FX+000"


@dataclass
class AboutContacts:
    email: str | None = None
    phone: str | None = None
    socials: list[ParsedSocial] = field(default_factory=list)


def fetch_channel_about_contacts(channel_id: str) -> AboutContacts:
    """Pull email, phone, and allowed socials from the channel About / More info page."""
    if not channel_id:
        return AboutContacts()

    data = _fetch_about_innertube(channel_id)
    source = "innertube"
    if data is None:
        data = _fetch_about_from_html(channel_id)
        source = "html"
    if data is None:
        # #region agent log
        _agent_log(
            "A",
            "channel_links.py:fetch_channel_about_contacts",
            "about_fetch_empty",
            {"channel_id": channel_id, "source": source},
        )
        # #endregion
        return AboutContacts()

    contacts = _contacts_from_data(data, raw_text_fallback=_data_as_text(data))
    # #region agent log
    _agent_log(
        "A",
        "channel_links.py:fetch_channel_about_contacts",
        "about_fetch_ok",
        {
            "channel_id": channel_id,
            "source": source,
            "email": bool(contacts.email),
            "phone": bool(contacts.phone),
            "social_count": len(contacts.socials),
            "social_platforms": [s.platform for s in contacts.socials],
        },
    )
    # #endregion
    logger.debug("About contacts for %s via %s", channel_id, source)
    return contacts


# Back-compat alias used by older call sites
def fetch_channel_about_socials(channel_id: str) -> list[ParsedSocial]:
    return fetch_channel_about_contacts(channel_id).socials


def _contacts_from_data(data: dict, raw_text_fallback: str = "") -> AboutContacts:
    description = _about_description_from_data(data)
    bio = parse_bio(description)

    socials: list[ParsedSocial] = []
    seen: set[tuple[str, str]] = set()

    def add(platform: str, value: str) -> None:
        platform = normalize_platform(platform)
        if platform not in ALLOWED_SOCIAL_PLATFORMS:
            return
        cleaned = value.strip().rstrip(".,);]}")
        if not cleaned:
            return
        key = (platform, cleaned.lower())
        if key in seen:
            return
        seen.add(key)
        socials.append(ParsedSocial(platform=platform, value=cleaned))

    for item in bio.socials:
        add(item.platform, item.value)

    for title, link in _links_from_data(data):
        url = _normalize_external_url(link)
        if not url:
            continue
        platform = platform_for_url(url)
        if not platform and title:
            platform = _platform_from_title(title) or ""
        add(platform, url)

    search_blob = "\n".join(
        part for part in (description, raw_text_fallback) if part
    )
    for match in _TME_RE.finditer(search_blob):
        add("telegram", f"https://t.me/{match.group(1)}")

    email = bio.email
    phone = bio.phone
    if not email:
        email = _first_clean_email(description) or _first_clean_email(raw_text_fallback)
    if not phone:
        from app.services.bio_parser import _first_phone

        phone = _first_phone(description)

    return AboutContacts(email=email, phone=phone, socials=socials)


def _fetch_about_innertube(channel_id: str) -> dict | None:
    """Browse channel → About engagement-panel continuation → JSON."""
    try:
        browse = _innertube_post(
            {"browseId": channel_id},
            referer=f"https://www.youtube.com/channel/{channel_id}",
        )
    except Exception as exc:
        # #region agent log
        _agent_log(
            "A",
            "channel_links.py:_fetch_about_innertube",
            "innertube_browse_error",
            {"channel_id": channel_id, "error": type(exc).__name__},
        )
        # #endregion
        logger.warning("Innertube browse failed for %s: %s", channel_id, exc)
        return None

    tokens = _about_continuation_tokens(browse)
    if not tokens:
        if _has_about_payload(browse):
            # #region agent log
            _agent_log(
                "A",
                "channel_links.py:_fetch_about_innertube",
                "innertube_inline_about",
                {"channel_id": channel_id},
            )
            # #endregion
            return browse
        # #region agent log
        _agent_log(
            "A",
            "channel_links.py:_fetch_about_innertube",
            "innertube_no_continuation",
            {"channel_id": channel_id},
        )
        # #endregion
        logger.info("No About continuation for %s; falling back to HTML", channel_id)
        return None

    last_empty_keys: list[str] = []
    for index, token in enumerate(tokens):
        try:
            about = _innertube_post(
                {"continuation": token},
                referer=f"https://www.youtube.com/channel/{channel_id}/about",
            )
        except Exception as exc:
            # #region agent log
            _agent_log(
                "A",
                "channel_links.py:_fetch_about_innertube",
                "innertube_continuation_error",
                {
                    "channel_id": channel_id,
                    "error": type(exc).__name__,
                    "token_index": index,
                },
            )
            # #endregion
            logger.warning(
                "Innertube About continuation failed for %s (token %s): %s",
                channel_id,
                index,
                exc,
            )
            continue

        if _has_about_payload(about):
            # #region agent log
            _agent_log(
                "A",
                "channel_links.py:_fetch_about_innertube",
                "innertube_about_hit",
                {
                    "channel_id": channel_id,
                    "token_index": index,
                    "token_count": len(tokens),
                    "runId": "post-fix",
                },
            )
            # #endregion
            return about
        last_empty_keys = list(about.keys())[:12]

    # #region agent log
    _agent_log(
        "A",
        "channel_links.py:_fetch_about_innertube",
        "innertube_about_empty",
        {
            "channel_id": channel_id,
            "token_count": len(tokens),
            "top_keys": last_empty_keys,
            "runId": "post-fix",
        },
    )
    # #endregion
    logger.info("Innertube About empty for %s; falling back to HTML", channel_id)
    return None


def _innertube_post(payload_extra: dict, *, referer: str) -> dict:
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": _INNERTUBE_CLIENT_VERSION,
                "hl": "en",
                "gl": "IN",
            }
        },
        **payload_extra,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _INNERTUBE_BROWSE_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": _UA,
            "Accept-Language": "en-US,en;q=0.9",
            "X-Youtube-Client-Name": "1",
            "X-Youtube-Client-Version": _INNERTUBE_CLIENT_VERSION,
            "Origin": "https://www.youtube.com",
            "Referer": referer,
            "Cookie": _CONSENT_COOKIE,
        },
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=15, context=context) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _about_continuation_tokens(data: dict) -> list[str]:
    """About-panel tokens first; shelf/other engagement panels last.

    Using tokens[0] blindly often hits a non-About continuation and returns empty.
    """
    preferred: list[str] = []
    fallback: list[str] = []

    def walk(node: object, path: str = "") -> None:
        if isinstance(node, dict):
            panel = node.get("showEngagementPanelEndpoint")
            if isinstance(panel, dict):
                path_l = path.lower()
                is_about_panel = any(
                    marker in path_l
                    for marker in (
                        "pageheaderrenderer",
                        "descriptionpreviewviewmodel",
                        "attributionviewmodel",
                        "aboutchannel",
                    )
                )
                for token in _continuation_tokens(panel):
                    if is_about_panel:
                        preferred.append(token)
                    else:
                        fallback.append(token)
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(data)

    ordered: list[str] = []
    seen: set[str] = set()
    for token in preferred + fallback:
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _about_continuation_token(data: dict) -> str | None:
    tokens = _about_continuation_tokens(data)
    return tokens[0] if tokens else None


def _continuation_tokens(node: object) -> list[str]:
    found: list[str] = []

    def walk(item: object) -> None:
        if isinstance(item, dict):
            command = item.get("continuationCommand")
            if isinstance(command, dict):
                token = command.get("token")
                if isinstance(token, str) and token.strip():
                    found.append(token.strip())
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(node)
    return found


def _has_about_payload(data: dict) -> bool:
    found = False

    def walk(node: object) -> None:
        nonlocal found
        if found:
            return
        if isinstance(node, dict):
            if "aboutChannelViewModel" in node or "channelExternalLinkViewModel" in node:
                found = True
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found


def _fetch_about_from_html(channel_id: str) -> dict | None:
    html = _fetch_about_html(channel_id)
    if not html:
        return None
    if _BOT_WALL_RE.search(html) and "ytInitialData" not in html:
        logger.warning("About HTML bot/consent wall for %s", channel_id)
        return None
    match = _YT_INITIAL_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _about_description_from_data(data: dict) -> str:
    candidates: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            about = node.get("aboutChannelViewModel")
            if isinstance(about, dict):
                desc = about.get("description")
                if isinstance(desc, str) and desc.strip():
                    candidates.append(desc)
            preview = node.get("descriptionPreviewViewModel")
            if isinstance(preview, dict):
                desc_obj = preview.get("description")
                if isinstance(desc_obj, dict):
                    content = desc_obj.get("content")
                    if isinstance(content, str) and content.strip():
                        candidates.append(content)
                elif isinstance(desc_obj, str) and desc_obj.strip():
                    candidates.append(desc_obj)
            meta = node.get("channelMetadataRenderer")
            if isinstance(meta, dict):
                desc = meta.get("description")
                if isinstance(desc, str) and desc.strip():
                    candidates.append(desc)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    if not candidates:
        return ""
    return max(candidates, key=len)


def _links_from_data(data: dict) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            view = node.get("channelExternalLinkViewModel")
            if isinstance(view, dict):
                title = _text_content(view.get("title"))
                link = _link_url_from_view(view)
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


def _link_url_from_view(view: dict) -> str:
    """Prefer redirect `q=` URL from commandRuns; fall back to display content."""
    link = view.get("link")
    redirect: str | None = None
    display = ""

    def dig(node: object) -> None:
        nonlocal redirect
        if redirect:
            return
        if isinstance(node, dict):
            endpoint = node.get("urlEndpoint")
            if isinstance(endpoint, dict):
                url = endpoint.get("url")
                if isinstance(url, str) and url.strip():
                    redirect = url.strip()
                    return
            meta = node.get("webCommandMetadata")
            if isinstance(meta, dict):
                url = meta.get("url")
                if isinstance(url, str) and "youtube.com/redirect" in url:
                    redirect = url.strip()
                    return
            for value in node.values():
                dig(value)
        elif isinstance(node, list):
            for value in node:
                dig(value)

    if isinstance(link, dict):
        display = _text_content(link)
        dig(link)
    elif isinstance(link, str):
        display = link.strip()

    return redirect or display


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


def _first_clean_email(text: str) -> str | None:
    from app.services.bio_parser import EMAIL_RE

    for match in EMAIL_RE.finditer(text or ""):
        email = match.group(1)
        if _EMAIL_NOISE.search(email):
            continue
        return email
    return None


def _fetch_about_html(channel_id: str) -> str | None:
    url = f"https://www.youtube.com/channel/{channel_id}/about"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": _CONSENT_COOKIE,
        },
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=context) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Failed to fetch About page for %s: %s", channel_id, exc)
        return None


def _data_as_text(data: dict) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def _normalize_external_url(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None

    if text.startswith("//"):
        text = "https:" + text

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
        if re.match(r"(?i)^[a-z0-9.-]+\.[a-z]{2,}(/|$)", text):
            text = "https://" + text
        else:
            return None

    return text


def _platform_from_title(title: str) -> str | None:
    t = title.strip().lower()
    # Exact / word matches only — substring "x" must not match "CoinDCX".
    if t in {"x", "twitter", "x.com", "twitter.com"}:
        return "x"
    if "telegram" in t or t in {"tg", "t.me"}:
        return "telegram"
    if "instagram" in t or t in {"ig", "insta"}:
        return "instagram"
    return None
