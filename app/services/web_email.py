from __future__ import annotations

import base64
import logging
import re
import ssl
import urllib.parse
import urllib.request
from html import unescape

from app.services.bio_parser import EMAIL_RE

logger = logging.getLogger(__name__)

BIG_CREATOR_SUBSCRIBERS = 100_000
_MAX_PAGES = 5
_FETCH_TIMEOUT = 12

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_EMAIL_NOISE = re.compile(
    r"(?i)("
    r"example\.com|sentry\.|wixpress|cloudflare|schema\.org|"
    r"google|youtube|gstatic|w3\.org|github\.com|microsoft\.|"
    r"png|jpg|jpeg|webp|svg|webpack|sentry-next"
    r")"
)

_SKIP_HOST_RE = re.compile(
    r"(?i)(^|\.)("
    r"youtube\.com|youtu\.be|instagram\.com|facebook\.com|fb\.com|"
    r"twitter\.com|x\.com|linkedin\.com|t\.me|telegram\.me|"
    r"tiktok\.com|wikipedia\.org|imdb\.com|bing\.com|microsoft\.com|"
    r"duckduckgo\.com|google\.com"
    r")$"
)

_BUSINESS_LOCAL = frozenset(
    {
        "hello",
        "hi",
        "contact",
        "business",
        "collab",
        "collabs",
        "collaboration",
        "partnerships",
        "partnership",
        "media",
        "press",
        "team",
        "info",
        "mail",
        "support",
        "bookings",
        "booking",
        "mgmt",
        "management",
        "enquiry",
        "inquiry",
        "work",
    }
)


def is_big_creator(subscribers: int | None) -> bool:
    return subscribers is not None and subscribers >= BIG_CREATOR_SUBSCRIBERS


def find_public_email(
    channel_name: str,
    *,
    extra_urls: list[str] | None = None,
) -> str | None:
    """Best-effort public email via Bing + candidate page scrape."""
    name = (channel_name or "").strip()
    if len(name) < 2:
        return None

    candidates: list[str] = []
    for url in extra_urls or []:
        normalized = _normalize_http_url(url)
        if normalized:
            candidates.append(normalized)

    try:
        candidates.extend(_bing_result_urls(name))
    except Exception as exc:
        logger.info("Web email Bing search failed for %s: %s", name, exc)

    # Prefer official-looking / contact pages first
    ranked_urls = _rank_urls(candidates, name)[:_MAX_PAGES]
    emails: list[str] = []
    for url in ranked_urls:
        try:
            html = _fetch_text(url)
        except Exception:
            continue
        emails.extend(_emails_from_html(html))

    best = _pick_best_email(emails, name)
    if best:
        logger.info("Web email found for %s: %s", name, best)
    return best


def _bing_result_urls(channel_name: str) -> list[str]:
    query = (
        f'"{channel_name}" (email OR collab OR contact OR "business@" OR "media kit")'
    )
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
    html = _fetch_text(url)
    html = unescape(html)

    found: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"[?&]u=(a1[A-Za-z0-9_\-%=]+)", html):
        raw = urllib.parse.unquote(match.group(1))
        dest = _decode_bing_u(raw)
        if not dest:
            continue
        dest = _normalize_http_url(dest)
        if not dest or dest in seen:
            continue
        if _should_skip_url(dest):
            continue
        seen.add(dest)
        found.append(dest)
    return found


def _decode_bing_u(value: str) -> str | None:
    raw = value[2:] if value.startswith("a1") else value
    pad = "=" * ((4 - len(raw) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + pad).decode("utf-8", errors="replace")
    except Exception:
        return None
    return decoded if decoded.startswith("http") else None


def _rank_urls(urls: list[str], channel_name: str) -> list[str]:
    tokens = _name_tokens(channel_name)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        low = url.lower()
        score = 0
        if any(t in low for t in tokens if len(t) >= 4):
            score += 3
        if any(k in low for k in ("contact", "about", "collab", "business", "media")):
            score += 2
        if low.rstrip("/").count("/") <= 3:
            score += 1
        scored.append((score, url))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, url in scored]


def _emails_from_html(html: str) -> list[str]:
    text = unescape(html or "")
    text = text.replace("&#64;", "@").replace("&commat;", "@")
    found: list[str] = []
    for match in re.finditer(r"mailto:([^\"'\s>?]+)", text, flags=re.I):
        email = urllib.parse.unquote(match.group(1)).split("?")[0].strip()
        if _is_clean_email(email):
            found.append(email.lower())
    for match in EMAIL_RE.finditer(text):
        email = match.group(1).strip()
        if _is_clean_email(email):
            found.append(email.lower())
    return found


def _pick_best_email(emails: list[str], channel_name: str) -> str | None:
    if not emails:
        return None
    tokens = _name_tokens(channel_name)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for email in emails:
        if email in seen:
            continue
        seen.add(email)
        local, _, domain = email.partition("@")
        score = 0
        local_l = local.lower()
        domain_l = domain.lower()
        for token in tokens:
            if len(token) >= 3 and (token in local_l or token in domain_l):
                score += 3
        local_root = re.split(r"[._+\-]", local_l)[0]
        if local_root in _BUSINESS_LOCAL:
            score += 2
        if domain_l.endswith((".com", ".in", ".co", ".net", ".org", ".io")):
            score += 1
        scored.append((score, email))
    scored.sort(key=lambda item: (-item[0], item[1]))
    # Prefer any positive score; otherwise first clean email
    if scored[0][0] > 0:
        return scored[0][1]
    return scored[0][1]


def _name_tokens(name: str) -> list[str]:
    parts = re.split(r"[^a-z0-9]+", name.lower())
    return [p for p in parts if len(p) >= 2 and p not in {"the", "and", "official", "yt"}]


def _is_clean_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    if _EMAIL_NOISE.search(email):
        return False
    if email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    if len(local) < 2 or "." not in domain:
        return False
    return True


def _should_skip_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return True
    if host.startswith("www."):
        host = host[4:]
    return bool(_SKIP_HOST_RE.search(host))


def _normalize_http_url(url: str) -> str | None:
    text = (url or "").strip()
    if not text:
        return None
    if text.startswith("//"):
        text = "https:" + text
    if not re.match(r"(?i)^https?://", text):
        if re.match(r"(?i)^[a-z0-9.-]+\.[a-z]{2,}(/|$)", text):
            text = "https://" + text
        else:
            return None
    if _should_skip_url(text):
        return None
    return text


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT, context=context) as resp:
        raw = resp.read()
        # Cap huge pages
        if len(raw) > 2_000_000:
            raw = raw[:2_000_000]
        return raw.decode("utf-8", errors="replace")
