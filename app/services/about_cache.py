from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.services.bio_parser import ParsedSocial, filter_allowed_socials, normalize_platform
from app.services.channel_links import AboutContacts

_TTL_SECONDS = 3600


@dataclass
class CachedContacts:
    email: str | None = None
    phone: str | None = None
    socials: list[ParsedSocial] = field(default_factory=list)


_cache: dict[str, tuple[float, CachedContacts]] = {}


def get_cached_contacts(channel_id: str) -> CachedContacts | None:
    entry = _cache.get(channel_id)
    if entry is None:
        return None
    expires_at, contacts = entry
    if time.monotonic() > expires_at:
        _cache.pop(channel_id, None)
        return None
    return contacts


def set_cached_contacts(channel_id: str, contacts: AboutContacts | CachedContacts) -> None:
    socials = filter_allowed_socials(list(contacts.socials))
    payload = CachedContacts(
        email=contacts.email,
        phone=contacts.phone,
        socials=socials,
    )
    _cache[channel_id] = (time.monotonic() + _TTL_SECONDS, payload)


def contacts_as_dict(contacts: CachedContacts | AboutContacts) -> dict:
    socials = filter_allowed_socials(list(contacts.socials))
    return {
        "email": contacts.email,
        "phone": contacts.phone,
        "socials": [
            {"platform": normalize_platform(s.platform), "value": s.value}
            for s in socials
        ],
    }


# Back-compat wrappers
def get_cached_socials(channel_id: str) -> list[ParsedSocial] | None:
    cached = get_cached_contacts(channel_id)
    if cached is None:
        return None
    return cached.socials


def set_cached_socials(channel_id: str, socials: list[ParsedSocial]) -> None:
    set_cached_contacts(channel_id, AboutContacts(socials=socials))


def socials_as_dicts(socials: list[ParsedSocial]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for s in filter_allowed_socials(socials):
        out.append({"platform": normalize_platform(s.platform), "value": s.value})
    return out
