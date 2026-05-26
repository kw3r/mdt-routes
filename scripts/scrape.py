"""Scrape the latest raider.io weekly-routes post and resolve every
embedded keystone.guru route into an MDT import string, then write
raiderio_weekly.json.

raider.io is a JS-rendered SPA, so we hit the JSON endpoint that powers
it (/api/news/weekly-routes) rather than parsing rendered HTML. Each
weekly post embeds keystone.guru routes via <iframe src="...">, and
keystone.guru exposes an MDT export at /ajax/{publicKey}/mdtExport.

Exit code 0 = wrote JSON, 1 = aborted (zero routes extracted -- preserve
the previous good file rather than overwriting with empty).
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

RIO_API_URL = "https://raider.io/api/news/weekly-routes"
KG_EXPORT_URL = "https://keystone.guru/ajax/{public_key}/mdtExport"
KG_ROUTE_URL = "https://keystone.guru/{public_key}"

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "raiderio_weekly.json"

# The raider.io weekly post uses <div id="{anchor}"></div> to delimit each
# dungeon section. Maintain this table when a new dungeon is added to the
# plugin's MAPPING_REGISTRY in main.lua.
ANCHOR_TO_INSTANCE_ID = {
    "algethar_academy":        2526,
    "magisters_terrace":       2811,
    "maisara_caverns":         2874,
    "nexus_point_xenas":       2915,
    "pit_of_saron":            658,
    "seat_of_the_triumvirate": 1753,
    "skyreach":                1209,
    "windrunner_spire":        2805,
}

ANCHOR_TO_DISPLAY_NAME = {
    "algethar_academy":        "Algeth'ar Academy",
    "magisters_terrace":       "Magister's Terrace",
    "maisara_caverns":         "Maisara Caverns",
    "nexus_point_xenas":       "Nexus-Point Xenas",
    "pit_of_saron":            "Pit of Saron",
    "seat_of_the_triumvirate": "Seat of the Triumvirate",
    "skyreach":                "Skyreach",
    "windrunner_spire":        "Windrunner Spire",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

ANCHOR_OR_IFRAME = re.compile(
    r'<div id="(?P<anchor>[a-z_]+)"></div>'
    r'|keystone\.guru/(?P<route>[A-Za-z0-9]+)/embed'
)

WEEK_LABEL_RE = re.compile(r"Week\s+\d+", re.IGNORECASE)


def fetch_latest_article(session: requests.Session) -> dict[str, Any]:
    """Return the latest weekly-routes article from raider.io's JSON API."""
    r = session.get(RIO_API_URL, timeout=30, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    payload = r.json()
    articles = payload.get("articles") or []
    if not articles:
        raise RuntimeError("raider.io returned zero articles from /api/news/weekly-routes")
    # Articles are ordered newest-first; take the first one that looks like
    # a weekly-route post.
    for art in articles:
        title = (art.get("title") or "")
        if "Weekly Route" in title:
            return art
    return articles[0]


def extract_dungeon_routes(content_html: str) -> list[tuple[str, str]]:
    """Walk the article body in document order, associating each
    keystone.guru iframe with the dungeon anchor that most recently
    preceded it.

    Returns a list of (anchor_id, kg_public_key) pairs."""
    pairs: list[tuple[str, str]] = []
    current_anchor: str | None = None
    for m in ANCHOR_OR_IFRAME.finditer(content_html):
        anchor = m.group("anchor")
        route = m.group("route")
        if anchor is not None:
            current_anchor = anchor if anchor in ANCHOR_TO_INSTANCE_ID else None
        elif route is not None and current_anchor is not None:
            pairs.append((current_anchor, route))
    return pairs


def fetch_mdt_string(session: requests.Session, public_key: str) -> str:
    """Call keystone.guru's MDT-export AJAX endpoint. Returns the raw
    MDT import string (starts with '!')."""
    url = KG_EXPORT_URL.format(public_key=public_key)
    r = session.get(
        url,
        timeout=30,
        headers={
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": KG_ROUTE_URL.format(public_key=public_key),
        },
        params={"useCache": "true"},
    )
    r.raise_for_status()
    body = r.json()
    mdt = body.get("mdt_string")
    if not isinstance(mdt, str) or not mdt.startswith("!"):
        raise RuntimeError(f"keystone.guru returned no mdt_string for {public_key!r}: {body!r}")
    return mdt


def derive_week_label(article: dict[str, Any]) -> str:
    """Pull a 'Week N' label out of the article body if present; fall
    back to the published date."""
    body = article.get("contentHtml") or ""
    m = WEEK_LABEL_RE.search(body)
    if m:
        return m.group(0)
    pub = article.get("published_at") or ""
    if pub:
        try:
            dt = datetime.strptime(pub[:10], "%Y-%m-%d")
            return dt.strftime("Week of %B %d")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("Week of %B %d")


def main() -> int:
    session = requests.Session()

    article = fetch_latest_article(session)
    pairs = extract_dungeon_routes(article.get("contentHtml") or "")
    if not pairs:
        print(
            "ABORT: no (dungeon, route) pairs extracted from latest article; "
            "raider.io article structure may have changed.",
            file=sys.stderr,
        )
        return 1

    week_label = derive_week_label(article)
    routes_by_instance: dict[str, list[dict[str, Any]]] = {}

    for anchor, public_key in pairs:
        inst_id = ANCHOR_TO_INSTANCE_ID[anchor]
        display = ANCHOR_TO_DISPLAY_NAME[anchor]
        try:
            mdt_string = fetch_mdt_string(session, public_key)
        except Exception as exc:
            print(
                f"WARN: failed to fetch MDT export for {anchor} / {public_key}: {exc}",
                file=sys.stderr,
            )
            continue
        routes_by_instance.setdefault(str(inst_id), []).append({
            "name": f"{display} - {week_label}",
            "mdt_string": mdt_string,
            "author": "Raider.IO",
            "score": None,
            "kg_public_key": public_key,
            "kg_url": KG_ROUTE_URL.format(public_key=public_key),
        })
        # gentle rate limit
        time.sleep(0.5)

    total = sum(len(v) for v in routes_by_instance.values())
    if total == 0:
        print(
            "ABORT: zero routes extracted; refusing to overwrite raiderio_weekly.json",
            file=sys.stderr,
        )
        return 1

    payload = {
        "post_url": article.get("url") or "https://raider.io/weekly-routes",
        "post_title": article.get("title") or "",
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": "",
        "week_label": week_label,
        "routes": routes_by_instance,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(
        f"Wrote {OUTPUT_PATH} with {total} route(s) across "
        f"{len(routes_by_instance)} dungeon(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
