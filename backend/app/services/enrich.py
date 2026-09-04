from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.models.schemas import SocialLink
from app.services.about_cache import (
    contacts_as_dict,
    get_cached_contacts,
    set_cached_contacts,
)
from app.services.bio_parser import normalize_platform
from app.services.channel_links import AboutContacts, fetch_channel_about_contacts

_MAX_WORKERS = 4
_MAX_IDS = 15

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


def enrich_channel_contacts(channel_ids: list[str]) -> dict[str, dict]:
    """Fetch About-page email/phone/socials in parallel (cached, best-effort)."""
    unique: list[str] = []
    seen: set[str] = set()
    for channel_id in channel_ids:
        cid = (channel_id or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        unique.append(cid)
        if len(unique) >= _MAX_IDS:
            break

    result: dict[str, dict] = {}
    to_fetch: list[str] = []
    cache_hits = 0

    for channel_id in unique:
        cached = get_cached_contacts(channel_id)
        if cached is not None:
            cache_hits += 1
            result[channel_id] = contacts_as_dict(cached)
        else:
            to_fetch.append(channel_id)

    # #region agent log
    _agent_log(
        "C",
        "enrich.py:enrich_channel_contacts",
        "enrich_start",
        {
            "requested": len(unique),
            "cache_hits": cache_hits,
            "to_fetch": len(to_fetch),
            "ids": unique[:5],
        },
    )
    # #endregion

    if not to_fetch:
        # #region agent log
        _agent_log(
            "C",
            "enrich.py:enrich_channel_contacts",
            "enrich_cache_only",
            {
                "summary": [
                    {
                        "id": cid,
                        "email": bool(payload.get("email")),
                        "phone": bool(payload.get("phone")),
                        "socials": len(payload.get("socials") or []),
                    }
                    for cid, payload in list(result.items())[:5]
                ]
            },
        )
        # #endregion
        return result

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(to_fetch))) as pool:
        futures = {
            pool.submit(_fetch_one, channel_id): channel_id for channel_id in to_fetch
        }
        for future in as_completed(futures):
            channel_id = futures[future]
            try:
                contacts = future.result()
            except Exception as exc:
                # #region agent log
                _agent_log(
                    "B",
                    "enrich.py:enrich_channel_contacts",
                    "enrich_fetch_exception",
                    {"channel_id": channel_id, "error": type(exc).__name__},
                )
                # #endregion
                contacts = AboutContacts()
            set_cached_contacts(channel_id, contacts)
            result[channel_id] = contacts_as_dict(contacts)

    # #region agent log
    _agent_log(
        "B",
        "enrich.py:enrich_channel_contacts",
        "enrich_done",
        {
            "summary": [
                {
                    "id": cid,
                    "email": bool(payload.get("email")),
                    "phone": bool(payload.get("phone")),
                    "socials": len(payload.get("socials") or []),
                }
                for cid, payload in list(result.items())[:8]
            ]
        },
    )
    # #endregion
    return result


# Back-compat name
def enrich_channel_socials(channel_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    full = enrich_channel_contacts(channel_ids)
    return {cid: payload.get("socials", []) for cid, payload in full.items()}


def enrich_creators_inplace(creators: list) -> None:
    """Fill missing email/phone/socials from About page for creator objects."""
    need_ids = [
        c.channel_id
        for c in creators
        if c.channel_id
        and (
            not c.email
            or not c.phone
            or not (c.socials and len(c.socials) > 0)
        )
    ]
    if not need_ids:
        return

    enriched = enrich_channel_contacts(need_ids)
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


def _fetch_one(channel_id: str) -> AboutContacts:
    return fetch_channel_about_contacts(channel_id)
