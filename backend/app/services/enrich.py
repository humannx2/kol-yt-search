from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from app.models.schemas import SocialLink
from app.services.about_cache import (
    contacts_as_dict,
    get_cached_contacts,
    set_cached_contacts,
)
from app.services.bio_parser import normalize_platform
from app.services.channel_links import AboutContacts, fetch_channel_about_contacts
from app.services.web_email import find_public_email, is_big_creator

_MAX_WORKERS = 4
_MAX_IDS = 15


@dataclass(frozen=True)
class EnrichTarget:
    channel_id: str
    channel_name: str = ""
    subscribers: int | None = None


def enrich_channel_contacts(
    channel_ids: list[str],
    *,
    targets: list[EnrichTarget] | None = None,
) -> dict[str, dict]:
    """Fetch About contacts (and web email for big creators) in parallel."""
    by_id: dict[str, EnrichTarget] = {}
    if targets:
        for target in targets:
            cid = (target.channel_id or "").strip()
            if not cid or cid in by_id:
                continue
            by_id[cid] = EnrichTarget(
                channel_id=cid,
                channel_name=(target.channel_name or "").strip(),
                subscribers=target.subscribers,
            )
            if len(by_id) >= _MAX_IDS:
                break

    if not by_id:
        for channel_id in channel_ids:
            cid = (channel_id or "").strip()
            if not cid or cid in by_id:
                continue
            by_id[cid] = EnrichTarget(channel_id=cid)
            if len(by_id) >= _MAX_IDS:
                break

    unique = list(by_id.keys())
    result: dict[str, dict] = {}
    to_fetch: list[EnrichTarget] = []

    for channel_id in unique:
        cached = get_cached_contacts(channel_id)
        target = by_id[channel_id]
        if cached is not None:
            if (
                not cached.email
                and is_big_creator(target.subscribers)
                and target.channel_name
            ):
                web_email = find_public_email(target.channel_name)
                if web_email:
                    cached.email = web_email
                    set_cached_contacts(channel_id, cached)
            result[channel_id] = contacts_as_dict(cached)
        else:
            to_fetch.append(target)

    if not to_fetch:
        return result

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(to_fetch))) as pool:
        futures = {
            pool.submit(_fetch_one, target): target.channel_id for target in to_fetch
        }
        for future in as_completed(futures):
            channel_id = futures[future]
            try:
                contacts = future.result()
            except Exception:
                contacts = AboutContacts()
            set_cached_contacts(channel_id, contacts)
            result[channel_id] = contacts_as_dict(contacts)

    return result


def enrich_channel_socials(channel_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    full = enrich_channel_contacts(channel_ids)
    return {cid: payload.get("socials", []) for cid, payload in full.items()}


def enrich_creators_inplace(creators: list) -> None:
    """Fill missing email/phone/socials from About (+ web email for big creators)."""
    targets = [
        EnrichTarget(
            channel_id=c.channel_id,
            channel_name=getattr(c, "channel_name", "") or "",
            subscribers=getattr(c, "subscribers", None),
        )
        for c in creators
        if c.channel_id
        and (
            not c.email
            or not c.phone
            or not (c.socials and len(c.socials) > 0)
        )
    ]
    if not targets:
        return

    enriched = enrich_channel_contacts([], targets=targets)
    for creator in creators:
        payload = enriched.get(creator.channel_id)
        if not payload:
            continue
        if not creator.email and payload.get("email"):
            creator.email = payload["email"]
        if not creator.phone and payload.get("phone"):
            creator.phone = payload["phone"]
        existing = {
            (normalize_platform(s.platform), s.value.lower()) for s in creator.socials
        }
        for item in payload.get("socials") or []:
            platform = normalize_platform(item["platform"])
            if platform not in {"x", "telegram", "instagram"}:
                continue
            key = (platform, item["value"].lower())
            if key in existing:
                continue
            creator.socials.append(
                SocialLink(platform=platform, value=item["value"])
            )
            existing.add(key)


def _fetch_one(target: EnrichTarget) -> AboutContacts:
    contacts = fetch_channel_about_contacts(target.channel_id)
    if contacts.email:
        return contacts
    if not is_big_creator(target.subscribers) or not target.channel_name:
        return contacts

    web_email = find_public_email(
        target.channel_name,
        extra_urls=list(contacts.website_urls),
    )
    if not web_email:
        return contacts
    return AboutContacts(
        email=web_email,
        phone=contacts.phone,
        socials=contacts.socials,
        website_urls=contacts.website_urls,
    )
