# Corporate-action history investigation — 7 October 2026

Original provider candles and saved reports are preserved. An event announcement
does not certify the provider's price/volume basis or account for distributed
securities. Nine unresolved instruments remain blocked by the gap check.

| Instrument | Cached gap date | Evidence reviewed | Outcome |
|---|---|---|---|
| COHANCE (formerly SUVENPHAR) | 24 March 2020 | Ten NSE BE candles are raw; adjacent EQ candles are adjusted for the later sourced 1:1 bonus. | Exact-row derived repair verified; no gap adjustment inferred. |
| ABREL (formerly Century Textiles) | 11 October 2019 | [UltraTech allotment filing](https://www.ultratechcement.com/content/dam/ultratechcementwebsite/pdf/stock-exchange-communication/Century%20Allotment.pdf) records one UltraTech share per eight Century shares, record date 14 October. | Demerger identified; historical identity/basis and entitlement accounting remain unresolved. |
| HEGAM | 7 September 2026 | [NSE instrument record](https://www.nseindia.com/get-quote/equity/HEGAM/HEG-Advanced-Materials-Limited) lists demerger ex-date and record date 7 September 2026. | Demerger identified; distribution, credit/tradability and provider bases remain unresolved. |
| IIFL | 30 May 2019 | [Issuer tax-basis filing](https://nsearchives.nseindia.com/corporate/IIFL_12062019180115_SEIntimationCostofAcquisition_285.pdf) and [scheme memorandum](https://nsearchives.nseindia.com/corporates/offerdocument/scheme/IM_IIFLSecurities.pdf) document securities/wealth demergers and 31 May record date. | Requires multiple resulting securities and fractional-entitlement treatment. |
| NMDC | 27 October 2022 | [NSE circular FAOP54132](https://archives.nseindia.com/content/circulars/FAOP54132.pdf) gives the demerger ex-date. NSE daily file gives raw 27 October open 92.25 and volume 38,603,184. | Cached open 27.88/volume 115,821,134 do not establish an exact consistent factor; earlier and later bases must be reconstructed. |
| SIEMENS | 7 April 2025 | [Resulting-company filing](https://www.siemens-energy-india.com/pdf/outcome-of-board-meeting-13-02-2026.pdf) records 7 April entitlement record date and June listing. | Demerger identified; unlisted entitlement valuation and execution timing remain unresolved. |
| TATACHEM | 4 March 2020 | [Issuer annual-report governance section](https://www.tatachemicals.com/tata/sites/default/files/2025-09/corporate-governance-report-2019-20_1758691856.pdf) describes price discovery/adjustment at the 5 March record date for Consumer Products demerger. | Requires resulting-company holdings and independently verified price/volume basis. |
| TATACOMM | 17 September 2019 | [Issuer January 2021 presentation](https://tatacommunications.com/hubfs/47271964/investor-presentations/pdfs/TCOM-Investor-Presentation-Jan-21.pdf) documents HPIL land demerger, 18 September record date and later October 2020 listing. | Unlisted entitlement valuation, credit and eventual sale must be modelled. |
| TMPV (formerly TATAMOTORS) | 14 October 2025 | [NSE circular FAOP70615](https://nsearchives.nseindia.com/content/circulars/FAOP70615.pdf) gives demerger ex-date 14 October; [issuer scheme release](https://www.tatamotors.com/press-releases/demerger-of-cv-business-undertaking-of-tata-motors-ltd-into-a-separate-listed-company/) states one resulting CV share per original share. | Requires both businesses and instrument identity/date mapping. |
| VEDL | 30 April 2026 | [NSE circular FAOP73857](https://nsearchives.nseindia.com/content/circulars/FAOP73857.pdf) gives demerger ex-date 30 April. | Multi-company distribution cannot be treated as a split. |

## Verified COHANCE repair

All OHLCV values of the ten cached BE sessions from 9–23 March 2020 match the
NSE daily files exactly by date, ISIN INE03QK01018, symbol SUVENPHAR and series BE.
Those rows were left on the raw basis. EQ samples on 24/25 March and 24 September
have prices at half the exchange value (within 0.026 rupees rounding tolerance)
and volumes exactly twice the exchange quantity. The 29 September sample matches
raw prices and volume after the bonus. The [issuer annual report](https://nsearchives.nseindia.com/corporate/SUVENPHAR_06082021185831_SUVENPHARAGMNoticeAR06082021.pdf)
documents the 1:1 bonus, 28 September record date and 29 September allotment.

Normalize only the ten exact documented BE rows: divide OHLC by two and multiply
volume by two. Keep exact mathematical half prices; do not invent provider tick
rounding. This changes the 24 March opening gap from -60% to -20%, consistent with
the exchange's actual opening move. It does not eliminate the real market loss.

`reference_data/candle_repairs.json` stores exact expected/replacement values,
per-file SHA256 and source URL, issuer basis evidence, and all four EQ controls.
The derived-input code rejects any matching date whose source row is neither the
documented bad row nor the verified replacement. Corrected rows are idempotent;
source cache and raw fingerprint checks remain intact. Historical paper cycles
halt when applied repairs to already processed dates differ from their saved
cycle evidence. Reconciliation never rewrites cash, fills or positions.

Corrections strictly before every saved cycle's maximum required signal, market,
RS and exit context need no historical decision reconciliation. Missing context
evidence requires a full check. Blue Sky's long lookback remains protected.
`scripts/reconcile_candle_repairs.py` can replay frozen, single-session, no-fill
checkpoints with old and new inputs. It emits evidence only if both complete
ledgers exactly match the saved ledger and every raw processed fingerprint
matches the frozen source. The record is bound to portfolio ID, complete ledger,
configuration, cycles, membership, fingerprints and repair policy hashes. Changes
invalidate it. Broader or fill-bearing checkpoints remain unsupported and halt.

No event is automatically converted into a split/bonus contract. Frozen backtest
inputs and repair evidence are retained with new results. Earlier reports keep
their original inputs and results; they need separate replays before comparison.

## Remaining reconstruction

For each of the nine demergers: verify the historical instrument identity, exact
exchange price/volume series, entitlement ratio, shares credit date, tradability,
fractional-share settlement and resulting-company price history. Then implement
and test an entitlement ledger before evaluating positions across the event.
Do not use tax cost-allocation percentages as market-price adjustment factors.
