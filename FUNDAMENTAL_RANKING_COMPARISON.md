# Fundamental ranking comparison

Period: 2026-06-01 to 2026-10-01; five positions; ₹10 lakh starting capital.

Identical frozen prices, universe, costs, signal rules and exits within each pair. Ranking is the only changed setting. This comparison does not add the live score/coverage buy filter.

Nifty 500 snapshot: 389 eligible price histories; 111 excluded by the frozen reference/warmup. Costs: 10 bps slippage per side, 35 bps buy charges, 50 bps sell charges. Next-open entries, 8% initial stop, 1.5% risk per trade, +25% winner exit, and the saved market-breadth gate. VCP uses 10-session contraction windows and 0.9 final-volume multiple. Both pairs share the same price-manifest and financial-evidence checksums.

| Screen | Priority | Return | Max drawdown | Trades | Win rate | Trades with usable score | Mean entry score |
|---|---|---:|---:|---:|---:|---:|---:|
| blue_sky | alphabetical | -11.09% | 14.26% | 24 | 20.83% | 22/24 | 50.00 |
| blue_sky | fundamental_score | 1.04% | 5.84% | 25 | 36.00% | 25/25 | 62.00 |
| vcp | alphabetical | 0.42% | 5.87% | 16 | 37.50% | 12/16 | 48.75 |
| vcp | fundamental_score | -6.80% | 11.86% | 21 | 33.33% | 17/21 | 55.88 |

Downloaded retrospectively. Only filings published by the decision time are used. The archive is incomplete and may omit intermediate quarters or earlier revisions; current constituent survivorship and archival selection bias remain. Missing, stale or flagged scores rank last; score ties use coverage then symbol. Ranking does not change the fundamental eligibility filter.

Scores use publication dates and verified raw filing checksums. Intermediate historical quarters are incomplete. The short window and current constituents limit conclusions. A higher score is a financial quality preference, not a forecast of price returns.

Run IDs: e35cbccbd328, 4de96e51f267, 357dfbc435ba, e37151bf1fcc
