# Composite investor pilot — local validation

The dashboard's **Composite strategy · paper portfolio** is an isolated ledger. It does not import existing portfolios, submit broker orders or deploy production code. Initial cash is ₹100,000. The four score weights remain fundamentals 40%, price behaviour 20%, technicals 20%, news 20%.

**Refresh data & scores** records current observations and runs the paper ledger. **Complete article reviews** reads accessible bodies in bounded batches, validates LLM citations, saves article summaries and raw LLM responses, then updates scores and the ledger. Unchanged complete reviews are reused; successful batches can be reused when another batch fails. Paywalls, oversized bodies and unreadable articles remain coverage gaps.

Paper entries require a complete score of at least 75, confidence of at least 80 and all existing breakout, quote, liquidity and risk gates. Signals are frozen with their observation dates, source hashes and model fingerprint. Only signals created after portfolio activation are eligible. Entries use the next completed session's open; daily bars cannot reproduce intraday execution. A newer same-session non-buy assessment cancels a pending signal.

Risk is 0.5% of equity per position including estimated costs at the planned stop. Allocation is at most 10% per stock, reserve cash 10%, maximum positions 10 and new entries 3 per session. Assumed fees are 10 bps and slippage 15 bps per side. Stops/targets account for opening gaps; stop wins when both touch within the same daily candle. Stop losses can exceed planned risk during gaps. Time exit is 20 observed sessions. Historical adjusted-price revisions pause positions for corporate-action reconciliation.

The dashboard displays cash, equity, realized profit/loss, pending decisions, completed exits, observed drawdown and return against Nifty's price index. Benchmark comparison starts at the first completed close on/after activation; missing observations remain unknown. Dividends, taxes, realistic intraday liquidity and corporate-action share accounting require additional validation. An exit-fill win rate is not a strategy-level success probability.

Ledger state and immutable snapshots are archived under PostgreSQL `assessments` alongside recommendations and forward 5/10/20-session outcomes. Official statements are saved under `feed_responses`; large PDF sources use numbered chunks with a document SHA-256. Verified financial reconciliations retain the company, period, basis, units and PDF page references. Do not use retrieval dates as historical publication dates.

Next validation needs genuinely future price observations, costs/slippage sensitivity, sector-specific fundamentals (particularly investment/financial companies), sufficient completed trades and comparison against the matched Nifty observation window. The model remains unvalidated. No newly generated real-money execution is enabled by this pilot.
