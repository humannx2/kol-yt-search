from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Only these socials are kept (plus email / phone as contact fields).
ALLOWED_SOCIAL_PLATFORMS = frozenset({"x", "telegram", "instagram"})

EMAIL_RE = re.compile(
    r"(?i)\b([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})\b"
)

PHONE_RE = re.compile(
    r"(?<!\w)"
    r"(?:"
    r"(?:\+?91[\s\-.]*)?(?:\d[\s\-.]*){10}"
    r"|"
    r"\+\d{1,3}[\s\-.]*(?:\d[\s\-.]*){7,14}"
    r"|"
    r"(?:\(?\d{2,5}\)?[\s\-.]*)?\d{3,5}[\s\-.]+\d{3,5}(?:[\s\-.]+\d{2,5})?"
    r")"
    r"(?!\w)"
)

URL_RE = re.compile(
    r"(?i)\b((?:https?://|www\.)?(?:instagram\.com|instagr\.am|twitter\.com|x\.com|"
    r"t\.me|telegram\.me)/[^\s<>\[\]()\"']+)"
)

HANDLE_LINE_RE = re.compile(
    r"(?im)^\s*(?:ig|insta|instagram|twitter|x|telegram|tg)\s*[:\-]\s*"
    r"@?([A-Za-z0-9._]{2,50})\s*$"
)

INLINE_HANDLE_RE = re.compile(
    r"(?i)\b(ig|insta|instagram|twitter|x|telegram|tg)\b\s*[:\-]?\s*"
    r"@([A-Za-z0-9._]{2,50})"
)

TELEGRAM_URL_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]+)"
)

PLATFORM_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("instagram", re.compile(r"(?i)(instagram\.com|instagr\.am)")),
    ("x", re.compile(r"(?i)(twitter\.com|(?<![a-z0-9])x\.com)")),
    ("telegram", re.compile(r"(?i)(t\.me|telegram\.me)")),
]

HANDLE_PLATFORM_MAP = {
    "ig": "instagram",
    "insta": "instagram",
    "instagram": "instagram",
    "twitter": "x",
    "x": "x",
    "telegram": "telegram",
    "tg": "telegram",
}


@dataclass(frozen=True)
class ParsedSocial:
    platform: str
    value: str


@dataclass(frozen=True)
class ParsedBio:
    email: str | None
    phone: str | None
    socials: list[ParsedSocial]


def parse_bio(description: str | None) -> ParsedBio:
    text = description or ""
    email = _first_email(text)
    phone = _first_phone(text, skip_email=email)
    socials = _extract_socials(text)
    return ParsedBio(email=email, phone=phone, socials=socials)


def filter_allowed_socials(socials: list[ParsedSocial]) -> list[ParsedSocial]:
    return [s for s in socials if normalize_platform(s.platform) in ALLOWED_SOCIAL_PLATFORMS]


def normalize_platform(platform: str) -> str:
    p = (platform or "").strip().lower()
    if p in {"twitter", "x"}:
        return "x"
    if p in HANDLE_PLATFORM_MAP:
        return HANDLE_PLATFORM_MAP[p]
    return p


def format_socials_export(socials: list[ParsedSocial] | list) -> str:
    parts: list[str] = []
    for item in socials:
        if isinstance(item, ParsedSocial):
            platform = normalize_platform(item.platform)
            if platform not in ALLOWED_SOCIAL_PLATFORMS:
                continue
            parts.append(f"{platform}:{item.value}")
        else:
            platform = getattr(item, "platform", None) or (
                item.get("platform") if isinstance(item, dict) else None
            )
            value = getattr(item, "value", None) or (
                item.get("value") if isinstance(item, dict) else None
            )
            platform = normalize_platform(str(platform or ""))
            if platform in ALLOWED_SOCIAL_PLATFORMS and value:
                parts.append(f"{platform}:{value}")
    return "; ".join(parts)


def is_india_or_unknown(country: str | None) -> bool:
    if country is None:
        return True
    code = country.strip().upper()
    if not code:
        return True
    return code == "IN"


def _first_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return match.group(1) if match else None


def _first_phone(text: str, skip_email: str | None = None) -> str | None:
    scrubbed = text
    if skip_email:
        scrubbed = scrubbed.replace(skip_email, " ")
    scrubbed = EMAIL_RE.sub(" ", scrubbed)
    scrubbed = URL_RE.sub(" ", scrubbed)

    for match in PHONE_RE.finditer(scrubbed):
        raw = match.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 10:
            continue
        if len(digits) > 15:
            continue
        return _normalize_phone(raw, digits)
    return None


def _normalize_phone(raw: str, digits: str) -> str:
    if digits.startswith("91") and len(digits) == 12:
        return f"+91 {digits[2:7]} {digits[7:]}"
    if len(digits) == 10:
        return f"+91 {digits[:5]} {digits[5:]}"
    if raw.startswith("+"):
        return re.sub(r"\s+", " ", raw).strip()
    return digits


def _extract_socials(text: str) -> list[ParsedSocial]:
    found: list[ParsedSocial] = []
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
        found.append(ParsedSocial(platform=platform, value=cleaned))

    for match in URL_RE.finditer(text):
        raw = match.group(1).strip().rstrip(".,);]}")
        url = raw if raw.lower().startswith("http") else f"https://{raw}"
        platform = platform_for_url(url)
        add(platform, url)

    for match in TELEGRAM_URL_RE.finditer(text):
        add("telegram", f"https://t.me/{match.group(1)}")

    for match in HANDLE_LINE_RE.finditer(text):
        line = match.group(0)
        handle = match.group(1)
        label = re.split(r"[:\-]", line, maxsplit=1)[0].strip().lower()
        platform = HANDLE_PLATFORM_MAP.get(label, "")
        add(platform, f"@{handle}")

    for match in INLINE_HANDLE_RE.finditer(text):
        label = match.group(1).lower()
        handle = match.group(2)
        platform = HANDLE_PLATFORM_MAP.get(label, "")
        add(platform, f"@{handle}")

    return found


def platform_for_url(url: str) -> str:
    host_path = url
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host_path = f"{parsed.netloc}{parsed.path}"
    except Exception:
        pass
    for platform, pattern in PLATFORM_HINTS:
        if pattern.search(host_path):
            return platform
    return ""
