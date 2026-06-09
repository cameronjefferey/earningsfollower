from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from app.config import get_settings


@dataclass
class Theme:
    key: str
    label: str
    tickers: list[str] = field(default_factory=list)


@dataclass
class Universe:
    themes: list[Theme]
    expand_with_fmp_peers: bool

    @property
    def seed_tickers(self) -> list[str]:
        seen: dict[str, None] = {}
        for theme in self.themes:
            for t in theme.tickers:
                seen.setdefault(t.upper(), None)
        return list(seen.keys())

    def themes_for(self, ticker: str) -> list[Theme]:
        ticker = ticker.upper()
        return [t for t in self.themes if ticker in {x.upper() for x in t.tickers}]


@lru_cache
def load_universe() -> Universe:
    settings = get_settings()
    with open(settings.universe_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    themes_raw = raw.get("themes", {}) or {}
    themes = [
        Theme(
            key=key,
            label=(cfg or {}).get("label", key),
            tickers=[str(t).upper() for t in (cfg or {}).get("tickers", [])],
        )
        for key, cfg in themes_raw.items()
    ]
    return Universe(
        themes=themes,
        expand_with_fmp_peers=bool(raw.get("expand_with_fmp_peers", True)),
    )
