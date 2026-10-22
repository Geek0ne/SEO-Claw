<div align="center">

# SEO-Claw

**Evidence-based SEO audit tool — it stays silent when it cannot prove a problem**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Crawl a site → run rule-based audits → produce a report you can actually act on.
Every finding requires positive evidence; when evidence is insufficient the tool
stays silent and explicitly lists the pages it could not audit.

[中文文档](README.md)

</div>

---

## Why another SEO tool

Most SEO tools hand you a 200-line red checklist: no priorities, no evidence, and
false positives mixed in. Following a false positive (e.g. "danger: Baiduspider
blocked") can destroy traffic when the block was intentional.

SEO-Claw inverts the contract: **every finding must be backed by positive
evidence, otherwise it is not reported.**

| | Typical SEO tools | SEO-Claw |
|---|---|---|
| Trigger threshold | "not detected" = missing | **Positive evidence** required |
| Site-level rules | always reported | **Silent** below coverage threshold |
| Crawl failures | hidden | Uncrawled pages are **disclosed** |
| Search volume | filled with 0 | Left **empty** when no data source |
| Accuracy claims | vendor-stated | **Re-verified against live pages** |

## Verified accuracy

Rules were exercised against 100+ real sites (blogs, e-commerce, docs,
government, Chinese communities, large corporate sites), then every finding was
re-checked against the live page — verifying facts, not plausibility. The
process uncovered both rule false-positives and bugs in the verification tooling
itself; all fixes are recorded with regression tests.

Verification artifacts ship with the repository:

- `docs/verification-ledger.md` — the verification ledger
- `tools/verify_*.py` — the re-checkers, re-runnable
- `reports/` — final-round JSON evidence

> **Honesty boundary**: sample re-verification covers only the most-reported
> rules; no blanket accuracy percentage is claimed for the rest. The `geo` pack
> (AI-search citability) is experimental and never loaded by default.

## Installation

Python 3.11+ required. Source install is the supported path (not yet published
to PyPI):

```bash
git clone https://github.com/Geek0ne/SEO-Claw.git
cd SEOClaw
pip install -e ".[api,dev]"     # CLI + Web/API + test tooling
```

## Quick start

```bash
seoclaw scan example.com                    # terminal report
seoclaw scan example.com -o report.md       # Markdown
seoclaw scan example.com --html out.html    # single-file HTML, client-ready
seoclaw rules                               # list loaded checks
```

Markets are additive (`base` always included): `--market google`, `--market baidu`,
`--market cnh_eco`, and the experimental `--market geo`.

**43 rules** in total: `base` 22, `google` 11, `baidu` 5, `cnh_eco` 1,
`geo` 4 (experimental, explicit opt-in).

## Web service & API

```bash
uvicorn seoclaw.main:app --port 8000
```

Browser UI with background scans and progress polling, a 36-operation REST API
(sites, jobs, issues, keywords, daily rank imports, SERP snapshot imports,
content briefs, rank alerts, usage quota, API
keys, ownership verification) and an MCP server exposing 3 read-only tools.

Before going public, read `DEPLOY.md` and run the guard smoke test:

```bash
./tools/guard_smoke.sh    # SSRF / rate-limit / concurrency / denylist
```

## Crawler politeness

Default 3 req/s per domain, `robots.txt` + `Crawl-delay` respected, adaptive
backoff on 429/403, circuit breaker after 5 consecutive failures. A 1000-page
site takes **~6.4 minutes in practice** (333 s is the wall-clock floor, and
87% of the measured 382 s was spent waiting on the limiter) — the limiter
releases serially, so adding concurrency does not shorten it. We keep 3 req/s
rather than raise the default to hit a prettier number; the early
"1000 pages ≤ 5 minutes" acceptance target was retired on 2026-10-22.

## Development

```bash
pytest backend/tests -q    # 737 tests (3 skipped without optional mcp)
```

Design rules the codebase enforces (see README.md for details): positive-evidence
only, silence below coverage thresholds, disclose unaudited pages, `null` over
`0` for missing data, opt-in persistence, experiment rules physically isolated.

## License

MIT
