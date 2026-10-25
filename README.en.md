<div align="center">

# 🦞 SEO-Claw

**Evidence-based site SEO audit — it would rather miss a finding than invent one**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-758%20✓-2EA44F?logo=pytest&logoColor=white)](#-development--testing)
[![Coverage](https://img.shields.io/badge/coverage-80.0%25-2EA44F)](#-development--testing)
[![License](https://img.shields.io/badge/license-MIT-FF9900)](#-license)
[![Code style](https://img.shields.io/badge/style-audit%20grade-black)](./DESIGN.md)

Crawl a site → run rule-based audits → produce a report you can act on directly.<br>
Every finding requires positive evidence; when evidence is insufficient the tool
stays silent — and explicitly lists the pages it could not audit.

**English** 　|　 [中文文档](README.md) 　·　 [Quick start](#-quick-start) · [Installation](#-installation)

</div>

---

## 📑 Table of contents

- [🎯 Why another SEO tool](#-why-another-seo-tool)
- [✨ Core features](#-core-features)
- [🔬 Verified accuracy](#-verified-accuracy)
- [📦 Installation](#-installation)
- [🚀 Quick start](#-quick-start)
- [🎛️ Commands & options](#️-commands--options)
- [📏 Rule coverage](#-rule-coverage)
- [🧾 Output formats](#-output-formats)
- [🌐 Web workbench & API](#-web-workbench--api)
- [🤝 Crawler politeness](#-crawler-politeness)
- [🚢 Deployment](#-deployment)
- [🏗️ Architecture](#️-architecture)
- [🧪 Development & testing](#-development--testing)
- [📐 Design principles](#-design-principles)
- [🗺️ Roadmap](#️-roadmap)
- [📜 License](#-license)

---

<a id="-why-another-seo-tool"></a>
## 🎯 Why another SEO tool

Most SEO tools hand you a 200-line red checklist: no priorities, no evidence,
false positives mixed in. Following one false positive (e.g. "danger: Baiduspider
is blocked") can zero out your traffic when the block was the site's own policy.

**SEO-Claw inverts the contract: every finding must be backed by positive,
traceable evidence — otherwise it is not reported.**

| | 🏭 Typical SEO tools | 🦞 SEO-Claw |
|---|---|---|
| 🎯 Trigger threshold | "not detected" = missing | **Positive evidence** required |
| 📊 Site-level rules | reported regardless of coverage | **Silent** below the coverage threshold |
| 🕳️ Crawl failures | hidden, report looks complete | Uncrawled pages are **disclosed** |
| 📈 Search volume | filled with 0 (implying "no demand") | Left **empty** when no data source |
| 🧪 Accuracy claims | vendor-stated, method opaque | **Re-verified against live pages**, method published |

<a id="-core-features"></a>
## ✨ Core features

| | Capability |
|---|---|
| 🧭 | **Rule engine** — 43 checks packaged per market (base / google / baidu / cnh_eco / geo), page-level and site-level tiers, experimental pack physically isolated from verified rules |
| 🕷️ | **Polite crawler** — BFS, rate limiting, adaptive backoff, circuit breaker, proxy rotation, resumable crawls, ETag/304 incremental scans |
| 🧾 | **Multi-format reports** — terminal / Markdown / JSON / single-file HTML (no external assets, offline-ready, client-deliverable) |
| 🩹 | **Fix packs** — turns findings into "before → after" actions in md / json / csv / diff; three confidence tiers, ambiguous cases go to a human instead of being faked |
| 📉 | **Rank monitoring data inlet** — daily rank/traffic CSV import (`rank-import`) + REST; bad rows are rejected line by line, interval-aggregated exports are refused |
| 🔍 | **SERP snapshot inlet** — competitor position import (CSV / JSON, `serp-import`) + REST; positions must be integer ranks, "average position" belongs to `rank-import` |
| 🔑 | **Keyword module** — corpus mining + term clustering, fully offline, deterministic, no API key required |
| 📝 | **Content brief** — competitor commonality from SERP snapshots, your positions from rank history, structure advice from your own pages; whatever is missing is stated as missing |
| 🤖 | **Optional LLM summary** — `--llm-summary`, works with any OpenAI-compatible endpoint (OpenRouter / DeepSeek / Ollama / self-hosted gateways) |
| 🖥️ | **Web workbench** — dashboard, one-click scans, issue triage, report exports, rank monitoring, multi-tenant API keys & quota |
| ⏱️ | **Persistent task queue & scheduled rescans** — scan jobs survive restarts; managed sites rescan on schedule (claim-before-enqueue: rather skip one run than hit the target twice) |
| 🗄️ | **Persistence** — 13 tables + Alembic migrations, SQLite by default, PostgreSQL for production |
| 🔌 | **MCP server** — 3 read-only tools so AI assistants can call the audit directly |
| 🎭 | **JS rendering** — opt-in via `--render-js` (needs Chromium, not shipped in the default image) |

<a id="-verified-accuracy"></a>
## 🔬 Verified accuracy

Every rule was exercised against **100+ real sites** (blogs, e-commerce, docs,
government, Chinese communities, large corporate sites), then each finding was
re-checked against the live page — verifying facts, not plausibility.

Two classes of issues were found and fixed along the way, both on record:

1. **🐛 Rule false positives** (e.g. JS-injected `<title>` judged missing, over-long
   Chinese titles under a translation view) — the judging logic was fixed, not just thresholds;
2. **🧰 Bugs in the tooling itself** (e.g. a sitemap-index misjudgment that produced
   12/58 false positives) — fixed, re-verified against real sites, regression tests added.

The full re-verification record ships with the repository:

- 📒 `docs/verification-ledger.md` — the verification ledger
- 🔧 `tools/verify_*.py` — the re-checkers, re-runnable yourself
- 🗂️ `reports/` — JSON evidence from each round
- 🖥️ The **"Quality & Verification" page** in the Web UI puts all of the above on
  screen: the live rule catalog, a golden-sample self-check that actually runs the
  rule engine, the three-tier accuracy calibration, and the source-verification ledger.

> **⚠️ Honesty boundary**: sampled re-verification only covers the most-reported
> rules; no blanket accuracy percentage is claimed for the rest. The experimental
> `geo` pack (AI-search citability) carries weaker evidence and is never loaded by default.

<a id="-installation"></a>
## 📦 Installation

Python **3.11+** required (development and CI run 3.12).

### Source install (the only supported path)

```bash
git clone https://github.com/Geek0ne/SEO-Claw.git
cd SEO-Claw
pip install -e ".[api,dev]"        # 📌 CLI + Web/API + test tooling
```

<details>
<summary>🔧 Other extras</summary>

```bash
# CLI scanning only (no FastAPI layer)
pip install -e .

# PostgreSQL persistence + MCP server
pip install -e ".[api,postgres,mcp]"
```

</details>

This installs two equivalent entry points: `seo-claw` and the alias `seoclaw`.

> 💡 The package is not on PyPI yet; `pip install seoclaw` / `pip install seo-claw`
> does not work at the moment.

<a id="-quick-start"></a>
## 🚀 Quick start

```bash
seoclaw scan example.com                  # 📟 report in the terminal
seoclaw scan example.com -o report.md     # 📄 Markdown
seoclaw scan example.com --html out.html  # 🌐 single-file HTML, client-ready
seoclaw scan example.com --json           # 🔗 JSON
seoclaw rules                             # 📏 see what will be checked
```

<a id="️-commands--options"></a>
## 🎛️ Commands & options

### `seoclaw scan <url>`

| Option | Default | Description |
|---|---|---|
| `--max-pages` | 100 | 🔢 page crawl limit |
| `--max-depth` | 6 | 📉 max BFS depth |
| `--rps` | 3.0 | ⏱️ requests per second per domain |
| `--market` | `base` | 🌍 market pack, repeatable: `base` / `google` / `baidu` / `cnh_eco` / `geo` |
| `--output, -o` | – | 📄 Markdown report path |
| `--html` | – | 🌐 single-file HTML report path |
| `--fixpack` | – | 🩹 fix-pack path (format by extension: `.md` / `.json` / `.csv` / `.diff`) |
| `--brand` | – | 🏷️ white-label delivery: report & fix-pack signed with this name (for agencies) |
| `--json` | – | 🔗 JSON output |
| `--db` | off | 🗄️ persistence path or connection string (no database is created unless given) |
| `--checkpoint` | – | 💾 resumable-crawl directory |
| `--incremental` | – | ♻️ incremental scan (ETag/304), requires `--checkpoint` |
| `--render-js` | off | 🎭 JS rendering (needs Chromium) |
| `--proxy` / `--proxy-file` | – | 🌉 proxies (repeatable / one per line in a file) |
| `--llm-summary` | off | 🤖 append an AI summary (OpenAI-compatible endpoint) |
| `--ignore-robots` | off | ⚠️ debugging your own site only |
| `--quiet, -q` | – | 🔇 quiet mode |

### `seoclaw rules`

Lists every loaded check (rule id, severity, title), split into page-level and
site-level sections.

### `seoclaw rank-import <csv> --db seo.db`

Imports **daily** rank/traffic data (GSC API / BigQuery / rank-tracker exports)
to drive rank monitoring and drop alerts. Column aliases are recognized
(`page` / `average position` / `query` …). ⚠️ The GSC **web UI** export is
interval-aggregated (no date column) and is rejected outright — a fake time
series is worse than none.

### `seoclaw serp-import <csv|json> --db seo.db --site example.com`

Imports one SERP capture (Top-10 competitor positions) to feed the content
brief's competitor dimension. CSV and JSON both work (format auto-detected from
extension and content when `--format` is absent); the same aliases are accepted
(`keyword`/`query`/`搜索词`, `url`/`link`, `position`/`rank`/`排名` …).

Two hard rules, both "rather reject than pollute":

- ⚠️ `--site` is **required**. Most rows in one capture belong to competitors;
  auto-matching by "most frequent domain" would credit your competitors with
  your data, so the tool does not guess.
- ⚠️ `position` must be an **integer rank** (1, 2, 3…). Decimal average positions
  belong to the rank time series via `rank-import`; mixing both pollutes the Top-N
  aggregates with fake positions.

When the file has no capture time, "today 00:00 UTC" is used for the snapshot
(and printed to the terminal). Re-importing the same (keyword, time, URL)
updates instead of duplicating. REST equivalents:
`POST /api/v1/sites/{id}/serp` and `GET /api/v1/sites/{id}/serp`.

<a id="-rule-coverage"></a>
## 📏 Rule coverage

**43 rules in total**, packaged per market and combined on demand:

| Pack | Market | Rules (page / site) | Enabled via |
|---|---|---|---|
| 🟢 `base` | Universal | **22** (15 / 7) | loaded by default |
| 🔵 `google` | Google | **11** (10 / 1) | `--market google` |
| 🟠 `baidu` | Baidu | **5** (3 / 2) | `--market baidu` |
| 💬 `cnh_eco` | WeChat Search | **1** (0 / 1) | `--market cnh_eco` |
| 🧪 `geo` | AI-search citability (experimental) | **4** (4 / 0) | `--market geo` (opt-in only) |

`--market` is additive (`base` is always included):

```bash
seoclaw scan example.com                     # 22 rules (base)
seoclaw scan example.com --market google     # 33 (base + google)
seoclaw scan example.com --market baidu      # 27 (base + baidu)
seoclaw scan example.com --market baidu --market google   # 38
```

**Coverage**: title / meta description / H1 / canonical / noindex / image alt /
internal anchor text / click depth / orphan pages / mixed content / structured
data / soft 404 / sitemap / robots.txt / hreflang / viewport / Open Graph /
ICP filing / WeChat Search indexability, and more.

### 🤫 Intentional silence

The tool **deliberately does not report** in these cases — reporting would be wrong:

- 🚫 The site deliberately blocks search engines → marked `possibly_intentional`, downgraded to INFO
- 📉 Site-level conclusions below the coverage threshold ("no internal links found" ≠ "the site has none")
- 🎭 Static checks on JS-rendered pages
- 🤔 Keyword stuffing / low-quality titles that may well be intentional

<a id="-output-formats"></a>
## 🧾 Output formats

| Format | Option | Use |
|---|---|---|
| 📟 Terminal | (default) | quick look |
| 📄 Markdown | `-o report.md` | archiving, review |
| 🔗 JSON | `--json` | programmatic processing |
| 🌐 Single-file HTML | `--html out.html` | no external assets, offline, client-deliverable |

Report structure: **health score** (0–100, per dimension) → **"top 5 things to
fix first"** → severity-collapsed issue list (each with evidence, impact, fix
hint and example code) → **disclosure of unaudited pages**.

<a id="-web-workbench--api"></a>
## 🌐 Web workbench & API

```bash
uvicorn seoclaw.main:app --port 8000
```

Open the browser and you get the **full workbench** (see
[docs/web-feature-matrix.md](docs/web-feature-matrix.md)):

- 📊 **Dashboard**: aggregate health metrics and a per-site card grid
- ⚡ **One-click scan**: background scan + progress polling, never blocks the browser
- 🧩 **Issue triage**: filter; mark single issues or whole root causes
  (open / acknowledged / fixed / false positive)
- 🧾 **Reports & exports**: md / html / json one click away
- 📈 **Trends & history**: health-score curve + scan job list
- 🩹 **Fix packs**: `GET /sites/{id}/fixpack` (md / json / csv / diff), brandable header
- 📥 **Data inlets**: daily ranks and SERP snapshots upload in the UI (file or
  paste); parsing lives server-side, shared with the CLI; each import gets a read-back table
- ⏱ **Scheduled managed rescans**: toggle on the overview page; execution params
  freeze into a snapshot at submit time
- 🔑 **Multi-tenant**: API keys (hashes only), quota, site ownership verification
- 🔌 **REST API**: 35 paths / 43 operations (per OpenAPI) + **MCP server** (3 read-only tools)
- 🔍 **Quality & verification**: rule catalog, golden-sample self-check (runs the
  rule engine on demand), accuracy calibration, source-verification ledger

<a id="-crawler-politeness"></a>
## 🤝 Crawler politeness

Politeness toward third-party sites is a hard constraint, hence an explicit
performance boundary:

- 🐢 Default **3 req/s**, `robots.txt` and declared `Crawl-delay` respected
- 📉 Adaptive backoff on 429/403; the circuit breaker aborts a domain after
  5 consecutive failures (to avoid extending a ban)
- ⏳ **A 1000-page site takes ~6.4 minutes in practice**: `3 req/s × 1000 pages ≈ 333 s`
  is the wall-clock floor (5.5 min); of the measured 382 s, 87% was spent waiting
  on the limiter. **Adding concurrency does not shorten it** — the limiter
  releases serially. This is a design trade-off, not a performance defect
- 🚫 **The default rate is not raised to make numbers look good**. Decision of
  2026-10-22: 3 req/s stays; the early "1000 pages ≤ 5 minutes" acceptance
  target is retired and replaced by the measured figure (see `PLAN.md`, M0 checklist)
- ✅ Measured on docs.python.org, 1000 pages: 382 s, 991 ok / 9 failed, resumable after interruption

<a id="-deployment"></a>
## 🚢 Deployment

```bash
docker compose up -d        # 🔒 binds 127.0.0.1:8000 only, by default
```

| Item | Notes |
|---|---|
| 🐳 `Dockerfile` | non-root, cached dependency layer, health check on `/api/v1/health` |
| 🧱 `docker-compose.yml` | data volume, log rotation (disk-full protection), SQLite / PostgreSQL switch |
| ☁️ `render.yaml` | one-click Render free-tier deploy (with free-tier limits documented) |
| 🚨 Pre-launch gate | `./tools/guard_smoke.sh` — 11 live cases across the SSRF / rate-limit / concurrency / denylist barriers |

> ⚠️ **All-green unit tests do not prove the container barriers are alive**;
> `guard_smoke.sh` is the last gate before launch.

Full selection rationale and cost measurements in **[DEPLOY.md](DEPLOY.md)**
(measured: CPU is not the bottleneck, peak memory ~100 MB, image 438 MB).

<a id="️-architecture"></a>
## 🏗️ Architecture

```
backend/seoclaw/
├── 🕷️ crawler.py       BFS crawl: rate limit / backoff / circuit breaker / proxies / resume
├── 📄 extract.py       HTML → Page (trafilatura content extraction)
├── 🧭 audit/
│   ├── ⚙️ engine.py    rule execution + site-level facts (coverage, hit_page_limit)
│   └── 📏 rules/       base / google / baidu / cnh_eco / geo
├── 🔑 keywords/        keyword expansion + clustering (fully offline)
├── 📝 brief.py         content brief (competitors from SERP, own rank from history)
├── 📉 rankdata.py      daily rank data inlet (CSV aliases + per-row errors + idempotent upsert)
├── 🔍 serpdata.py      SERP snapshot inlet (CSV / JSON, integer ranks only)
├── 🩹 fixpack.py       fix packs: findings → "before → after", three confidence tiers
├── 🤖 llm.py           optional LLM summary (OpenAI-compatible, 0 extra dependencies)
├── ⏱️ tasks.py          persistent job queue: claim → run → finish, restart-safe
├── ⏰ scheduler.py     scheduled rescans: due sites become queue entries
├── 🧾 log.py           structured logging
├── 🗄️ db/              13 tables + Alembic migrations
├── 🧾 report.py        Markdown report
├── 🌐 report_html.py   single-file HTML report
├── 🖥️ web/             online workbench (quick-scan + progress polling)
├── 🔌 api/             FastAPI layer (auth / quota / ownership / exports)
└── 🧰 mcp_server.py    MCP server (3 read-only tools)
```

**~19,200 lines of implementation · ~12,100 lines of tests · 758 tests (all
green in practice; line counts cover `.py` under `backend/seoclaw` and `backend/tests`).**

### 🗄️ Database

13 tables: `sites` / `crawl_jobs` / `pages` / `issues` / `keywords` /
`serp_snapshots` / `content_briefs` / `suggestions` / `api_keys` /
`rank_alert_acks` / `usage_events` / `rank_history` / `scan_tasks`.

```bash
cd backend && alembic -c migrations/alembic.ini upgrade head
```

> ⚠️ Production **must go through Alembic migrations**. `create_all` only
> guarantees an empty database can start — it will not add columns to an
> existing one; mixing them produces the silent "works in tests, 500s in prod" failure.

<a id="-development--testing"></a>
## 🧪 Development & testing

```bash
git clone https://github.com/Geek0ne/SEO-Claw.git
cd SEO-Claw
pip install -e ".[api,dev]"
pytest backend/tests -q
```

- ✅ **758 tests** # 758 tests, all green locally; 1 module-level skip
  (`test_mcp_server.py`, 3 cases) when the optional `mcp` extra is not installed
- 📊 Coverage 80.0% (measured locally with `pytest --cov`; CI gate 78%, 2.0
  points of headroom). Repeated runs drift between 79.99%–80.03% — the drift is
  one `create_all` line in `db/session.py` sharing a sqlite file across tests;
  the root cause and fix are filed as tech debt in PLAN. The gap is closing:
  `cli.py` went from 28% to 41% (command-level cases for `rank-import` / `rules`
  / argparse dispatch), while `api/routes.py` remains the 37% thin wiring layer —
  the rules, DB and parsing layers all have cases; **the era of hand-smoking the
  wiring layer should end**. Follow the command-level template in
  `test_cli_persist.py` (real files + real temp DB), **not by lowering the gate**
- 🔢 The README's own numbers have a regression net (`test_docs_stats.py`): table
  count and names are checked against `Base.metadata.tables`, paths/operations
  against `app.openapi()`, and the CN/EN test counts and coverage badges must
  agree. **A number written in two places will drift** — this is not pedantry
- 🤖 **CI, two jobs**: ① full tests + coverage + CLI smoke + wheel build;
  ② `guard_smoke.sh` real-container acceptance (four barriers)
- 🧰 On some machines `run.sh` wraps local dependency installation (`.deps/`
  isolation + `PYTHONPATH`), see comments in the script

### 📚 Related documents

| Document | Content |
|---|---|
| 🚢 [DEPLOY.md](DEPLOY.md) | deployment options, cost measurements, upgrade guide |
| 🎨 [DESIGN.md](DESIGN.md) | Web UI design system (single source of truth) |
| 📋 [REQUIREMENTS.md](REQUIREMENTS.md) · [PLAN.md](PLAN.md) | product requirements & evolution plan |
| 🌐 [docs/web-feature-matrix.md](docs/web-feature-matrix.md) | Web feature matrix & completion log |
| 🤝 [CONTRIBUTING.md](CONTRIBUTING.md) | contribution guide & the bar for new rules |
| 🔒 [SECURITY.md](SECURITY.md) | security policy & attack surface |
| 📝 [CHANGELOG.md](CHANGELOG.md) | release notes |

<a id="-design-principles"></a>
## 📐 Design principles

These constraints were hardened by real lessons; they are code-level rules:

1. 🎯 **Only report findings with positive evidence** — "not detected" does not imply "absent"
2. 🤫 **Site-level rules must stay silent below the coverage threshold**
3. 📋 **Reports must disclose unaudited pages** — never let "not audited" read as "no problem"
4. 🚫 **Without a paid data source, search volume stays `null`**, never 0
5. 🔒 **No database is created unless `--db` is given** — never create files unasked
6. 🛟 **A persistence failure must not kill the report** — enhancement layers fail without dragging down the core
7. 🧪 **Experimental rules are physically isolated** — the `geo` pack needs explicit opt-in

<a id="️-roadmap"></a>
## 🗺️ Roadmap

The current release focuses on the accuracy and deliverability of technical SEO
audits. Planned directions (see [REQUIREMENTS.md](REQUIREMENTS.md) / [PLAN.md](PLAN.md)):

- 📈 SERP rank & traffic monitoring, anomaly alerts (both inlets are live: daily
  ranks `rank-import` / `POST /rankings`, SERP snapshots `serp-import` / `POST /serp`;
  plug in a real data source and it works)
- ✍️ Page rewriting & the second half of the execution loop: fix packs already
  emit "before → after"; next come platform adapters (WordPress/Shopify plugins)
  and automated PR diffs
- 🆚 Competitor tracking & content-gap analysis (competitor positions already
  stored and feeding briefs; cross-keyword gap comparison and competitor sets not yet)
- 📅 Content calendar & batch briefs
- 📤 One-click export to PR diff / PDF / Excel

<a id="-license"></a>
## 📜 License

[MIT](LICENSE) © 2026 Geek0ne
