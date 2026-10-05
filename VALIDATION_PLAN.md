# Frozen validation plan — registered 5 October 2026 (IST)

This is a research protocol, not a claim of profitability or a live-trading launch.
Current data is not cleared for edge validation. Do not optimize around these
acceptance criteria or call a previously inspected period an untouched holdout.

## Candidate

Use one VCP candidate, Nifty 500, next-session open, starting research cash
₹1,000,000. Freeze these values before new experiments:

| Rule | Value |
|---|---|
| VCP windows | Three consecutive 10-session windows |
| Breakout volume multiple | 1.5 |
| Final contraction volume multiple | 0.8 |
| Trend average | 50 sessions |
| Long trend / rising long trend | Enabled / enabled |
| Minimum turnover | ₹50,000,000 |
| Candidate priority | 126-session RS |
| Market gate | Enabled, breadth ≥40%, coverage ≥80% |
| Risk / initial stop / positions | 1% / 8% / 5 |
| Breakeven / winner exit / maximum hold | 1R / 50-day trail / 120 sessions |
| Slippage per side | 20 bps |
| Buy / sell charges | 15 / 25 bps aggregate assumptions |

Freeze the complete config, source-tree hashes, input hashes and membership
snapshot in the run. The fee values are assumptions, not a verified brokerage
schedule. Stress slippage to 40 bps per side without changing other rules.

## Data gate

Before performance evaluation: resolve or explicitly exclude every suspect
instrument with sourced evidence; reconcile corporate actions and raw/adjusted
price AND volume bases; verify listing dates for IPO experiments; obtain dated
membership and delisted history for historical edge claims. Record exclusions
and their effect. The official listing import covers 497/500 current-universe symbols; three unmatched instruments remain unverified. Listing dates alone do not clear the other data gates.
An anomaly detector passing is insufficient. Unsupported mergers/demergers and
provider revisions remain blocks, not permission to infer split factors.

## Retrospective diagnostics

All dates through 5 October 2026 must be treated as previously available research
data. Once cleared, use chronological yearly evaluations and cost sensitivity,
reporting returns, drawdown, expectancy, exposure, turnover, concentration and
trade count. Compare with a dated Nifty 500 total-return benchmark. Do not
substitute an equal-weight basket or a price-only index and call it the TRI.
If benchmark data is unavailable, mark the comparison unavailable.

Separate bullish, bearish and sideways diagnostics using a rule fixed beforehand
(for example benchmark above/below its dated 200-session average and its slope).
These are diagnostics, not independently unseen validation. Never train using
later periods or change rules after seeing a validation outcome without declaring
a new candidate and a new holdout.

## Prospective holdout and graduation

Reserve observed sessions from **6 October 2026** onward. This document does not
create or replace a production portfolio or allocate capital. Observe the frozen
candidate for at least 12 months AND 100 closed trades, whichever comes later.
It cannot graduate before the data gate passes.

Provisional acceptance rules: positive net expectancy under baseline and stressed
costs; maximum marked drawdown no greater than 20%; positive excess return over
the chosen total-return benchmark across the complete observation window; no
unresolved accounting/data failures. Report uncertainty and concentration: a
small sample or one dominant winner requires continued observation, not a pass.
These thresholds express this candidate's research gate, not universal investment
standards. Passing paper simulation still requires a separate live execution test.

For edge decay, assess rolling 50-trade expectancy, six-month drawdown and data
health against the frozen baseline after each month. Record meaningful failures
in the decision log; investigate before changing rules. Never reset losing history.
No new automation or notification is created by this plan.

## Decision log

| Date (IST) | Decision | Evidence / implication |
|---|---|---|
| 5 Oct 2026 | No global split adjustment | Nestlé sample has prices adjusted by approximately 20 and volume by exactly 20; another adjustment would corrupt it. |
| 5 Oct 2026 | Reject prelisting inputs for four sourced IPOs | Preserve provider cache, filter only derived research inputs; do not invent listing dates for other instruments. |
| 5 Oct 2026 | Quarantine PRIVISCL | Corporate restructure plus implausible old price history; no verified reconstruction yet. |
| 5 Oct 2026 | Keep edge gate closed | Historical membership, remaining actions and provider history still unresolved. |
