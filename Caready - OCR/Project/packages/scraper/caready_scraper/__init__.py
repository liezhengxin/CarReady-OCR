"""New-car OTR price ingestion adapters (§6.2).

Interface-only at M0. Adapters land at M4.

Two implementations are planned behind `PriceSourceAdapter`:

    csv   Manual CSV import. The GUARANTEED FALLBACK and the CI default.
    web   Source-specific web adapters, selectors in config not code.

**The CSV adapter is not a stopgap.** It is the path that always works, and the
one the pricing model depends on when everything else breaks.

Legal position, stated plainly: scraping third-party sites may violate their
terms of service and is operationally fragile. A site redesign silently
degrades price data, which corrupts the residual-value anchor that every
prediction depends on. The mitigations implemented are:

  * `robots.txt` respected, per-domain rate limiting, identifying User-Agent
  * conditional requests and caching, so we re-fetch as little as possible
  * selectors in `config/price_selectors.yaml`, so a redesign is a config edit
  * a run yielding zero rows ALERTS AND FAILS rather than returning stale data

Whether to scrape at all, or to licence a data feed, is a commercial decision
for Caready - see docs/OPEN_ITEMS.md #3. This package exists so that decision
can be reversed without touching the pricing model.
"""

__version__ = "0.1.0"
