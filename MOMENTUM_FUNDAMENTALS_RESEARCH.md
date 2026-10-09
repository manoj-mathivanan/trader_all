# Fundamentals before momentum entry

Implemented at the user's request. New dashboard momentum forms enable the fundamentals filter; old saved configurations retain their original behavior for faithful replay. The dashboard's **Test fundamentals filter** action runs a matched pair: the chosen reference configuration without the gate and the identical configuration with it. Prices, costs, capital, stock selection and one frozen fundamental archive are shared.

Entry requires score >=60, evidence coverage >=80%, financial period age <=180 days, and no scorer risk flags. The score reuses the project's transparent earnings/revenue growth, profitability, debt, interest coverage, cash generation, pledge and concern checks. Thresholds are editable and saved per experiment. The same quality gate applies before either a long or short position; this is a universe-quality screen, not a bearish fundamentals thesis. Blocked selected slots are not replaced.

Only verified archived NSE filing bytes are used, with checksum and identity validation. Historical snapshots are reconstructed in publication order. The exact entry time in IST determines which version is available, including same-day releases. Today’s score never substitutes for a missing historical score. These are retrospectively reconstructed research snapshots, not evidence of a contemporaneously made trading decision. The archive lacks some historical quarters/revisions and financial-sector coverage; that can materially bias the subset that trades.

## Matched results

| Window | Without gate | With gate | Allowed / checked |
|---|---:|---:|---:|
| March 2026 | −5.1040%, 54 trades | 0.0000%, 0 trades | 0 / 54 |
| 26 August–4 September 2026 | −1.0548%, 21 trades | +0.1161%, 3 trades | 3 / 21 |

March: 25 entries lack historical financial evidence. The other 29 have stale, incomplete evidence and fail the score/coverage thresholds. Zero trades is not validation of an improvement.

August–September: 18 entries blocked, including nine with missing historical scores. Allowed trades: HINDCOPPER long on 26 August (score 80, coverage 80%, +₹3,047.35); LT short on 26 August (score 60, coverage 85%, +₹388.40); MARUTI long on 2 September (score 60, coverage 80%, −₹2,274.75). Net +₹1,161.00 on ₹10 lakh starting capital after assumed charges and slippage. Different sizing under the evolving equity curve is recomputed by the backtester, rather than subtracting blocked trades from the original ledger.

This is an exploratory three-trade positive result, far below the research requirement of 100 trades and multiple positive windows. No strategy has been promoted. No February 2025 archived versions exist, so a strict February fundamental gate would block every entry; later filings must not be backfilled into that period.

March comparison `89ca875c2cee`, filtered run `47ecdcf8d557`. August–September comparison `bce9e414edbb`, filtered run `92aa48f278b7`. Each saved report includes every proposed entry's pass/block reasons, scores, coverage, period age, filing availability and check time; both matched reports retain the archive hash and frozen evidence.
