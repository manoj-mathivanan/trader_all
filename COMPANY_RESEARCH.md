# Automatic company research

The Fundamentals page adds company-quality scoring and an LLM that searches websites
for financial filings and multiple recent news articles itself. Users select a stock;
they do not supply websites, articles or financial figures. News reviews remain advisory.
Stored fundamental scores now enforce configurable prospective buy screens. Historical
backtests, stops and position sizing remain unchanged. See [Quarterly bulk pull and buy screens](FUNDAMENTALS_PULL.md).

## Workflow

1. Refresh the market universe and download daily history as usual.
2. Open **Fundamentals**, choose an existing technical screen and scan candidates.
3. Select **Research stock**. The thesis and provisional disposition are optional.
4. The worker searches company/exchange disclosures and recent reporting, then extracts
   financial metrics, supportive catalysts, risks, contradictions and unknowns.
5. Read the saved review and clickable citations. Reviews remain in the prospective
   journal and can be exported. Rejected candidates remain in the journal too.

Research runs as an inspectable job. Failed or interrupted jobs do not fabricate reviews
or figures. Research the technical shortlist one company at a time; there is no whole-
universe paid search. The separate NSE fundamentals pull covers the complete market-data
universe, with quarter-aware caching and automatic prospective buy restrictions.

## Server connection

For Windows local setup, run `./setup-research.ps1` from PowerShell in the project folder.
It prompts for the API key without displaying it, verifies key/model access using the
Models endpoint, and stores the key with Windows DPAPI encryption in
`%LOCALAPPDATA%/TraderCompanyResearch/openai.json`, outside the repository. The directory
has an ACL restricted to the current Windows user. Default model: `gpt-5.4-mini`, which
supports web search and structured outputs. The access check does not verify billing
or generate/search; the first company research job verifies those capabilities.
Stop the existing local server, then run `./start.ps1` to load the saved connection.
Existing process environment variables take precedence over the saved local values.
The encrypted record can be unlocked only by the same Windows account; it is not a
portable server credential. Run setup again to replace it. Never paste keys into chat.

Model reference: [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

Set `OPENAI_API_KEY` and `TRADER_NEWS_MODEL` in the server process environment. Choose
a model supporting Responses web search and structured outputs. No key or model is
silently selected, and Python does not load `.env.example` automatically. Keys are
never returned to the dashboard. Production requires the existing Basic Auth settings
before exposing a paid research action. This feature does not configure credentials.

The first Responses request requires `web_search`, includes source metadata and caps
built-in tool calls at eight. The second extracts structured data from the retrieved
report without tools. Both set `store=false`. Provider request failures are reported
without saving request headers or secrets. Live search requires a configured API key;
provider behavior is tested using mocked responses.

Official references: [Web search](https://developers.openai.com/api/docs/guides/tools-web-search)
and [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Evidence contracts

- Exact company identity uses name, NSE symbol and ISIN. Unconfirmed identity rejects
  the review. Web content is untrusted evidence and cannot authorize actions.
- Cited URLs must appear in provider search metadata or URL annotations; generated links
  alone are insufficient. This verifies source discovery, not the model's interpretation.
- Automatic financial scores use direct official NSE integrated Ind-AS HTML filings;
  LLM-generated financial figures never enter the score. Downloads validate symbol,
  ISIN, INR units, reporting dates and accounting basis. Original HTML, SHA-256 hashes,
  parsed rows and calculation inputs are retained under `data/company/filings`.
  The timestamp encoded in the NSE filename is recorded with an explicit notice and
  checked against the board approval date; it is not inferred by the LLM.
- Quarterly revenue/PAT growth requires matching prior-year dates, units and basis.
  NSE's integrated-filing index discovers the latest and matching prior-year quarters
  directly, independently of LLM-selected links. Old month-name dates and INR actuals
  are supported; amounts are converted to INR before comparing rupees/lakhs/crores.
  Only the reporting-quarter column is used, never the YTD column. Nonpositive prior
  bases and conflicting prior revisions leave growth unknown. An explicit unmodified
  opinion can populate the filing-specific auditor check, not the governance check.
- Annual NSE filings now populate ROE (total PAT / average total equity), ROCE
  ((PBT + finance costs) / average (total assets - current liabilities)), debt/equity
  (current and non-current borrowings plus explicit lease liabilities / total equity),
  interest coverage ((PBT + finance costs) / finance costs) and operating cash flow/PAT.
  Annual profit and finance costs use the YTD column; fourth-quarter figures are not
  annualized. Average balance-sheet ratios require two annual filings. Nonpositive
  denominators and unsupported fields remain unknown. These are the stated calculation
  conventions, and may differ from published vendor ratios.
- This adapter does not parse BSE filings, company PDFs, bank/NBFC taxonomies,
  P/E or promoter pledges. Placeholder zero ratios are
  ignored. Unsupported or inaccessible documents leave financial metrics unknown;
  failures appear in the saved review. Downloads allow only the supported official
  NSE host/path, reject redirects and cap size at 2 MB and discovery at eight files.
  Requests identify the reader with `TraderCompanyResearch/1.0`; NSE stalls the default
  Python HTTP client user-agent on this machine. Connect/read timeouts are 5/20 seconds.
- Legacy LLM-derived financial snapshots remain in the audit files but are excluded
  from the current screener. The report, discovered links, response IDs and usage
  remain preserved alongside direct filing artifacts.
- Recent-news findings require known publication dates in the preceding 30 calendar
  days. Missing dates cannot support favourable recent news. The LLM groups coverage
  of the same event, but independent corroboration is not guaranteed.
- Two non-opinion source domains are required for `supportive`; conflicting or adverse
  evidence yields `mixed` or `adverse`. Insufficient evidence remains explicit. Verdicts
  classify evidence and do not predict prices or issue buy instructions.
- The financial snapshot and review are frozen prospectively. Today's evidence must
  not be used as historical point-in-time inputs. Reviews store the selected technical
  configuration and the latest price-catalog context; signal and review dates may differ.

## Experimental score

Missing metrics earn zero points; coverage is the sum of known metric weights. Financial
periods older than 180 days, reported auditor/governance concerns, and promoter pledging
above 20% flag review. No adverse search results does not establish clean governance.

| Criterion | Non-financial weight | Bank/NBFC weight |
|---|---:|---:|
| Latest quarter revenue growth YoY ≥ 10% | 15 | 15 |
| Latest quarter PAT growth YoY ≥ 10% | 20 | 20 |
| Annual/trailing annual ROE ≥ 12% | 15 | 15 |
| Annual/trailing annual ROCE ≥ 15% | 10 | — |
| Debt/equity ≤ 1 | 10 | — |
| Annual/trailing annual interest coverage ≥ 3 | 5 | — |
| Annual operating cash flow / positive PAT ≥ 0.8 | 5 | — |
| Net NPA ≤ 2% | — | 15 |
| Capital adequacy ≥ 15% | — | 15 |
| Promoter shares pledged ≤ 5% | 10 | 10 |
| Explicit evidence of no auditor concern | 5 | 5 |
| Explicit evidence of no governance concern | 5 | 5 |

These are research thresholds, not sector regulatory requirements. IPOs may have limited
financial history; negative-base profit growth stays unknown. Valuation and acceleration
are not scored yet. Technical scans reuse swing predicates, warmup, RS, breadth, listing
and corporate-action evidence. They exclude today's possibly incomplete IST session,
stale history, quarantines and detected price discontinuities.

## Storage and evaluation

Research artifacts use the existing ignored data directory: `company/evidence.json`,
`company/reviews_index.json`, and `company/reviews/<id>.json`. Later research never rewrites
old reviews. Optional manual import APIs remain compatible but are not the primary UI.

Tests cover scoring, missing values, sector rules, timestamps, actual search execution,
identity, URL provenance, per-metric sources, news recency, provider failures, queued jobs,
immutable journals, API boundaries, automatic controls, filtering and HTML escaping.
Evaluate the configured entry filters prospectively, including rejected
candidates, net expectancy, drawdown and missed winners.
