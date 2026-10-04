# Screen and backtest configuration guide

This guide describes the current implementation in this repository, as inspected on 4 October 2026. It explains the fields in **Add a new screen** and **Backtests → New backtest**, including defaults, accepted values, formulas and interactions. Examples illustrate the software's behavior; they are not trading recommendations.

## 1. What you are configuring

A **screen** is a reusable set of stock qualification filters. It stores a name, a pattern and thirteen filter values. It does not store capital, entry mode, position priority, risk, exits, dates or execution costs.

A **backtest** combines those filters with a test period and portfolio execution assumptions. Selecting a screen copies its pattern and filter values into the form. You can change them for that experiment without changing the saved screen. Changing the screen selection replaces the filter fields, so select the screen before making individual adjustments.

The engine is long-only and uses daily OHLCV candles: open, high, low, close and volume. All symbols share one cash balance. A session means an available daily candle, not a calendar day. A 50-session average is therefore different from 50 calendar days.

### Units and conventions

| Unit | Meaning | Example |
|---|---|---|
| Sessions | Daily observations for a symbol | 10 sessions is usually about two trading weeks. |
| Percent (`pct`) | Enter a percentage number, not a decimal fraction | Enter `8` for 8%. |
| Multiple | A ratio to a baseline | `1.5` means 150% of the baseline. |
| Rupees | Absolute INR amount | `50000000` = ₹5 crore. |
| Basis points (`bps`) | 1 bps = 0.01%; 100 bps = 1% | `10` bps = 0.1% per side. |
| R | Initial entry-to-stop price risk | Entry ₹100 and stop ₹92 give 1 R = ₹8 per share. |

All listed range endpoints are inclusive unless explicitly written as `> 0`. Session/count parameters must be integers. Numeric configuration values must be finite, and unknown API fields are rejected.

## 2. Configure a screen

### Screen name — `name`

- **New-screen UI value:** `My screen`. **API:** required, 1–80 characters.
- Use a name that identifies the assumptions, such as `VCP volume 1.5 RS 80`.
- The UI trims leading/trailing whitespace before saving. The name does not affect signals.
- Saving the exact same name again replaces the screen with that name-derived ID. The server retains the latest 100 saved screens. `id` and `created_at` are generated metadata, not inputs.

### Base screen — `pattern`

- **New-screen UI/API default:** `vcp`.
- **Choices:** `vcp`, `blue_sky`, `multiyear`, `ipo`.
- This chooses the pattern predicate. All four require the common trend, turnover and signal-volume rules described below.

| Pattern | Exact qualification in this engine |
|---|---|
| VCP — `vcp` | Three consecutive prior windows must show strictly declining normalized price ranges and strictly declining average volumes. The final window must satisfy the volume dry-up limit. The signal close must exceed the final window's high. |
| Blue sky — `blue_sky` | The signal close must exceed the highest prior high in the available history, limited by the configured lookback cap. There is no additional base-depth or contraction test. |
| Multi-year breakouts — `multiyear` | The signal close must exceed the high of the configured long base, and that base must satisfy the multiyear depth limit. |
| IPO base — `ipo` | The signal close must exceed the configured short base's high, and that base must satisfy the short-base depth limit. The current engine does **not** verify listing age or that this is the first base. |

The API also accepts legacy `breakout` for backtests, but the screen-saving API and screen dropdown do not. Its filter predicate uses the short-base rules like IPO; its execution behavior differs as explained later.

### Filter applicability

All thirteen filters remain visible and are saved even when the selected pattern does not use them. An inactive field does not add a condition just because you entered a value.

| Parameter | VCP | Blue sky | Multi-year | IPO / legacy breakout |
|---|---|---|---|---|
| `base_days` | Pivot fill calculation only | No | No | Signal base and pivot |
| `max_depth_pct` | No | No | No | Signal depth |
| `volume_multiple` | Yes | Yes | Yes | Yes |
| `sma_days` | Yes | Yes | Yes | Yes |
| `require_long_trend` | Yes | Yes | Yes | Yes |
| `require_rising_long_trend` | Yes | Yes | Yes | Yes |
| `min_rs_rating` | Backtest entry filter | Backtest entry filter | Backtest entry filter | Backtest entry filter |
| `min_turnover` | Yes | Yes | Yes | Yes |
| `vcp_window_days` | Yes | No | No | No |
| `vcp_volume_multiple` | Yes | No | No | No |
| `blue_sky_lookback_days` | No | Signal and pivot | No | No |
| `multiyear_base_days` | No | No | Signal and pivot | No |
| `multiyear_max_depth_pct` | No | No | Signal depth | No |

`min_rs_rating` is stored with the screen, but is applied by the simulation after the pattern predicate qualifies. The pure pattern predicate itself does not compute RS.

### Base length (sessions) — `base_days`

- **UI default:** `15`. **Screen API/backtest model default:** `25`. **Range:** 5–250.
- Uses exactly this many completed candles immediately before the signal candle for IPO and legacy breakout. It is a fixed measurement window, not an automatically detected base of at least this length.
- The base high is the maximum high, and the base low is the minimum low in that window. The signal candle is excluded.
- A larger window can raise the breakout ceiling and capture a wider/deeper structure; it need not simply reduce signals in every dataset.
- **VCP interaction:** VCP signal qualification uses `vcp_window_days`, but pivot entry uses `base_days` to calculate the execution pivot. With defaults, qualification checks a 10-session high while the pivot fill uses a 15-session high. `next_open` and `close` do not use this pivot fill calculation.

### Maximum base depth (%) — `max_depth_pct`

- **UI default:** `35`. **API/model default:** `30`. **Range:** > 0 through 80.
- Used only for IPO and legacy breakout.
- Formula: `depth_pct = (base_high - base_low) / base_high × 100`.
- A base with high ₹100 and low ₹75 has 25% depth. It passes a limit of 30 and fails a limit of 20. Equality passes.
- Lower values require shallower bases. This parameter has no effect on VCP, Blue sky or Multi-year qualification.

### Volume / prior 50-session mean — `volume_multiple`

- **UI default:** `1`. **API/model default:** `1.5`. **Range:** 0.1–10.
- All patterns require `signal_volume >= mean(prior 50 volumes) × volume_multiple`.
- The mean excludes the signal candle. With a prior mean of 100,000 shares, `1.5` requires at least 150,000 shares on the signal candle.
- Higher values strengthen volume confirmation; below 1 allows below-average signal volume. This is share volume, not rupee turnover.

### Trend SMA (sessions) — `sma_days`

- **UI/API default:** `50`. **Range:** 5–250.
- Every pattern requires the signal close to be **strictly above** the simple mean of the latest `sma_days` closes, including the signal close.
- A close equal to the average fails. This is a price-above-average test; it does not require this average to slope upward.
- Increasing the length changes the trend horizon and can increase required warmup. At least 50 prior sessions are still needed for volume and turnover even if this value is less than 50.

### Require price above 200-day SMA — `require_long_trend`

- **UI/API default:** `false`. **Values:** `true` / `false`.
- If enabled, the signal close must also be strictly above its 200-session SMA, including the signal close.
- This supplements `sma_days`; it does not replace it. Backtest preparation requires at least 200 prior sessions when enabled.

### Require rising 200-day SMA (20 sessions) — `require_rising_long_trend`

- **UI/API default:** `false`. **Values:** `true` / `false`.
- Requires the current 200-session SMA to be strictly greater than its value 20 sessions earlier, **and** the signal close to be above the current 200-session SMA.
- Therefore enabling this also enforces the long-trend price test even if `require_long_trend` is unchecked.
- Requires 220 warmup sessions in backtest preparation. This is a comparison between two averages, not a requirement for an increase on every intervening session.

### Minimum 126-session RS percentile — `min_rs_rating`

- **UI/API default:** `0`. **Range:** 0–100. `0` disables the threshold.
- Computes each eligible symbol's return on the signal date: `close_today / close_126_sessions_earlier - 1`.
- Converts those returns to percentile ranks among loaded, non-excluded symbols with a candle on that date and sufficient history. It is relative to this run's dataset, not a benchmark index and not a proprietary Banana rating.
- Higher values retain stronger relative performers. A threshold of `80` requires a percentile of at least 80; it does not require an 80% price return.
- Tied returns receive their average rank. A single eligible symbol receives percentile 0. Missing RS fails a positive threshold.
- Enabling a positive threshold requires at least 126 prior sessions. Changing the universe or exclusions can change the percentile even for identical stock prices.
- `candidate_rank` is separate: this field controls eligibility; candidate ranking controls which eligible symbols get scarce cash or position slots.

### Minimum average turnover (₹) — `min_turnover`

- **UI/API default:** `50000000` (₹5 crore per session). **Range:** 0–1,000,000,000,000.
- All patterns require `mean(close × volume over prior 50 sessions) >= min_turnover`.
- The signal candle is excluded. This is a daily traded-value proxy based on close × volume, not actual intraday traded value or a volume participation limit.
- Higher values demand more liquidity. `0` effectively removes this threshold for ordinary nonnegative data.

### VCP contraction window (sessions) — `vcp_window_days`

- **UI/API default:** `10`. **Range:** 3–60. **Applies:** VCP only.
- Splits the `3 × vcp_window_days` candles immediately before the signal into three consecutive equal windows, oldest to newest.
- For each window, range is `(highest_high - lowest_low) / highest_high`; volume is the mean share volume.
- Requires `range_old > range_middle > range_recent` and `volume_old > volume_middle > volume_recent`. Equality fails either contraction sequence.
- The signal close must exceed the most recent window's highest high. Larger windows examine contractions over a longer period and increase warmup if `3 × window` exceeds the other requirements.

### VCP final volume / 50-session mean — `vcp_volume_multiple`

- **UI default:** `0.9`. **API/model default:** `0.8`. **Range:** > 0 through 1. **Applies:** VCP only.
- Requires `mean_volume_recent_window <= mean_volume_prior_50 × vcp_volume_multiple`.
- For a prior 50-session mean of 100,000, `0.9` permits a final contraction-window mean up to 90,000; `0.5` permits up to 50,000.
- Lower values require stronger volume dry-up. This tests the prior contraction window; `volume_multiple` independently tests the breakout candle's volume expansion.

### Blue-sky prior high lookback (sessions) — `blue_sky_lookback_days`

- **UI/API default:** `5000`. **Range:** 50–5000. **Applies:** Blue sky only.
- The signal close must be strictly above the highest high in the preceding `min(configured_lookback, available_prior_sessions)` candles.
- The setting is a cap, not a minimum history requirement. A symbol with 100 prior sessions and a cap of 5000 is compared with those 100 sessions.
- A larger value can include older resistance. A smaller value produces a rolling-high test. Even 5000 cannot establish a true lifetime high when the downloaded history is shorter than the listing's lifetime.
- The same lookback determines the Blue-sky pivot fill level. There is no enforced 252-session minimum in the predicate, despite the pattern registry's descriptive history label.

### Multiyear base length (sessions) — `multiyear_base_days`

- **UI/API default:** `260`. **Range:** 252–2500. **Applies:** Multi-year only.
- Measures a fixed prior window of this length. The signal close must exceed its highest high, and its depth must pass `multiyear_max_depth_pct`.
- Also determines the pivot fill ceiling. Larger values extend the structure being measured and require more pre-test history. The engine does not independently detect how many years a base has existed.

### Multiyear maximum base depth (%) — `multiyear_max_depth_pct`

- **UI/API default:** `50`. **Range:** > 0 through 90. **Applies:** Multi-year only.
- Uses the same high-to-low depth formula as `max_depth_pct`, over `multiyear_base_days`.
- Lower values demand shallower long bases. `max_depth_pct` does not add another depth condition for this pattern.

## 3. Data settings required before a backtest

These are shared **Settings → Market data** fields, not saved-screen or per-backtest inputs. The backtest uses the selected universe at submission and saves its snapshot.

| Parameter | Default / accepted values | Behavior |
|---|---|---|
| `universe` — Universe | `nifty50`; choices `nifty50`, `nifty500` | Selects the stored constituent list and symbol datasets. It changes signals, competition for cash, RS ranks and market breadth. Refresh the universe and fetch data for the selected list. |
| `start` — History from | `2018-10-01`; date | Requested download start. Choose sufficiently earlier than the backtest start for warmup. This is different from the test's `start`. |
| `end` — History through | `2026-10-01`; date | Requested download end. Must be after history start; the range must be at most 3653 calendar days. This is different from the test's `end`. |

Saving settings does not download candles. Refresh the universe and fetch daily history through Market data. Fetching requires a saved Upstox access token (20–10,000 characters); running against existing local history does not require a new token fetch.

Missing symbol files stop preparation. Each symbol's requested download range must cover the chosen test interval. Symbols with insufficient pre-test warmup are excluded and listed in the report. Requested coverage does not guarantee a candle on every date: holidays, suspensions and recent listings may leave gaps.

## 4. Configure a backtest

Every filter in section 2 also appears in the backtest form and has the same meaning. The following fields complete the experiment.

### Strategy — `strategy` (UI selector)

The current dropdown offers only **Swing Pattern** (`swing_patterns`). Intraday/scalping are planned. This selector is a UI control; `strategy` is not a field in `BacktestConfig` and is not submitted by its schema-based form reader. Do not include it in a direct backtest API payload.

### Screen — `screen` (UI selector)

Defaults to **VCP**, unless opening a different built-in/saved screen or cloning a run. Built-in selector IDs are `builtin:vcp`, `builtin:blue_sky`, `builtin:multiyear`, `builtin:ipo`; saved screens use generated custom IDs.

This copies values into the form's actual `pattern` and filter fields. `screen` itself is not a `BacktestConfig` API field. The run records the copied configuration, rather than a live reference that follows later screen edits.

### Run name — `name`

- **UI/model default:** `Breakout experiment`. **Range:** 1–80 characters.
- Identifies the run in reports. It has no effect on trading behavior. Use a name that makes comparisons recognizable.
- Adjust & rerun appends ` · revised`; the total name must still satisfy the length limit.

### Test from / Test through — `start`, `end`

- **API:** both dates are required; `start < end`. **New UI run:** suggested from the downloaded safe window. Cloning preserves the run's dates.
- Both boundaries are inclusive for available candles. Earlier candles supply indicators and can provide the previous-session signal for an entry at the beginning of the test.
- This means a next-open/pivot trade on the first test session can originate from a signal just before `start`; warmup dates do not become reported portfolio sessions.
- Every symbol is liquidated at its last available candle within the interval, using that candle's close plus sell slippage/charges. A symbol whose history ends early can therefore exit before the requested `end`.
- Dates need not themselves be trading sessions, but there must be actual candles in the interval. The UI blocks an end beyond its coverage window; backend preparation also validates requested coverage.

### Starting capital (₹) — `capital`

- **UI/model default:** `1000000` (₹10 lakh). **Range:** ₹1,000–₹10,000,000,000.
- Initial shared cash balance. Capital is not separately assigned to each stock.
- Position sizing uses portfolio equity at the session open; buying is constrained by remaining cash including buy charges. The model has no borrowing to fund an entry.
- Larger capital can change whole-share rounding and cash availability; it does not relax screen conditions.

### Minimum comparison warmup (sessions) — `minimum_warmup_sessions`

- **UI/model default:** `50`. **Range:** 50–2500.
- Minimum number of a symbol's candles strictly before the test start. A symbol that fails is excluded for the entire run, rather than becoming eligible later in that run.
- Effective requirement is `max(minimum_warmup_sessions, required_warmup_for_rules)`:

| Rule | Required warmup component |
|---|---|
| Every pattern | At least 50 and `sma_days` |
| VCP | Also `3 × vcp_window_days` |
| IPO / legacy breakout | Also `base_days` |
| Multi-year | Also `multiyear_base_days` |
| Above 200-session SMA | Also 200 |
| Rising 200-session SMA | Also 220 |
| Positive RS threshold or RS candidate priority | Also 126 |
| Blue sky | No requirement to fill the full Blue-sky lookback cap |

For example, Multi-year with a 260-session base still needs 260 prior sessions even if this field says 50. VCP with 60-session windows needs at least 180.

The UI's safe-window suggestion uses an additional session buffer for the prior signal, and is calculated when opening the dialog. It is not recalculated for every subsequent filter edit; its calculation also does not explicitly include `3 × vcp_window_days`. Backend preparation enforces the actual configuration. Check exclusions and fetch more history or move the start if needed.

### Entry price — `entry_mode`

- **UI/model default:** `pivot`. **Choices:** `pivot`, `close`, `next_open`.

| Choice | Signal timing and raw fill before costs |
|---|---|
| Pivot breakout — `pivot` | Requires a qualifying previous-session signal. On the following available symbol session, raw fill is `max(open, pivot)`, provided the high reaches that price. If not reached, the entry is skipped; there is no persistent pending order. |
| Close breakout — `close` | For the four current patterns, qualifies on today's completed candle and enters at today's close. This assumes execution at the very close used to confirm the signal. |
| Next session open — `next_open` | Requires a qualifying previous-session signal and fills at the following available symbol session's open. Useful when comparing with the paper engine's next-open timing. |

The pivot is the prior base high: `base_days` for VCP/IPO, `multiyear_base_days` for Multi-year, and capped prior history for Blue sky. Note the VCP signal-window/pivot-window difference in section 2.

For current-pattern `pivot` and `close` entries, initial protection, position aging and winner management start on the **next** available session. The entry-day low is not used to retroactively stop the position because daily candles cannot establish intraday ordering. Next-open entries can hit the initial stop on their entry day. All entry prices are then adjusted by buy slippage.

**Legacy `breakout`:** always uses previous-session qualification and next-open fills, irrespective of the stored `entry_mode`; its winner management uses the percentage fallback rather than the moving-average branches.

### Simultaneous signal priority — `candidate_rank`

- **UI/model default:** `alphabetical`. **Choices:** `alphabetical`, `rs_126`.
- `alphabetical` considers symbols in sorted symbol order.
- `rs_126` considers the highest signal-date RS percentile first, then highest 126-session return, then symbol order. It requires 126-session warmup even if `min_rs_rating` is zero.
- Ranking matters when cash or `max_positions` prevents taking all candidates. It does not itself impose a minimum strength threshold.
- Ranking uses the completed signal date: today's date for current-pattern close entry; the previous available symbol session for next-open/pivot and legacy breakout. Missing RS sorts behind valid scores.

### Risk per trade (%) — `risk_pct`

- **UI/model default:** `1.5`. **Range:** > 0 through 5.
- Sets the sizing budget to `equity_at_open × risk_pct / 100`, rather than allocating that percentage of capital to the purchase.
- Quantity is the smaller of the risk-limited and cash-limited whole-share counts, rounded down. Entries with fewer than one share are skipped.
- The sizer includes modeled fees and exit slippage in unit risk:

```text
buy_rate = buy_cost_bps / 10000
sell_rate = sell_cost_bps / 10000
slip = slippage_bps / 10000
unit_risk = fill - initial_stop + fill × buy_rate + initial_stop × (sell_rate + slip)
risk_quantity = floor(equity_at_open × risk_pct / 100 / unit_risk)
cash_quantity = floor(available_cash / (fill × (1 + buy_rate)))
quantity = max(0, min(risk_quantity, cash_quantity))
```

At equity ₹10 lakh, 1.5% gives ₹15,000 risk budget. With zero costs, fill ₹100 and stop ₹92, risk sizing gives 1,875 shares costing ₹187,500, subject to cash and capacity.

The budget is per position, not a portfolio-wide aggregate loss cap. Multiple positions can each consume a budget, and gaps can exceed the modeled stop loss. Within a session, candidates use the same open-equity basis but progressively reduced available cash; this also applies to the model's close entries.

### Initial stop (%) — `stop_pct`

- **UI/model default:** `8`. **Range:** > 0 through 50.
- Initial stop is `slippage_adjusted_buy_fill × (1 - stop_pct / 100)`.
- Defines initial price risk for sizing and the R trigger. Wider stops generally reduce risk-limited quantity; tighter stops increase it, subject to available cash.
- For an existing protected position, an open at/below the stop exits at the open; otherwise a low at/below the stop exits at the stop. Sell slippage and charges then apply. The stop is a simulated trigger, not a guaranteed net exit price.

### Winner exit — `winner_exit`

- **UI/model default:** `trail_50d`. **Choices:** `trail_50d`, `trail_30w`, `take_25`.
- Winner management begins only when the close reaches the `breakeven_r` threshold. Until then, initial protection and holding/end-of-data exits remain active.

| Choice | Implementation after the R trigger |
|---|---|
| 50-day trailing exit — `trail_50d` | Raises the stop to the maximum of the previous stop, cost-adjusted breakeven and current 50-session SMA. |
| 30-week trailing exit — `trail_30w` | Same, using a **150-daily-session SMA** as the 30-week approximation. It does not aggregate weekly candles. If unavailable, uses the percentage fallback. |
| Take profit at +25% — `take_25` | Exits at the close when that close is at least 25% above entry **and** the R trigger is satisfied. Before that, once the R trigger is satisfied, cost-adjusted breakeven and the percentage fallback can raise the stop. This is not an intraday limit order. |

Stops only rise; they do not fall with the moving average. Close-based stop updates become active next session. A take-profit exit uses the same close that meets its conditions, with sell costs applied.

### Skip weak markets — `skip_weak_markets`

- **UI/model default:** `false`. **Values:** `true` / `false`.
- If enabled, new entries need sufficient signal-date market breadth as defined below. Existing positions keep their exit rules.
- This is a gate across the run's eligible stock datasets, not a test against an external index. Insufficient-data exclusions can change the breadth calculation.

### Minimum market breadth (%) — `market_breadth_pct`

- **UI/model default:** `40`. **Range:** 0–100. Active only when `skip_weak_markets` is true.
- Breadth is `100 × eligible_symbols_above_200_session_SMA / eligible_symbols` on the signal date. Above means strictly above; equality does not count.
- Eligible symbols must have a candle on that date with index at least 200 in their dataset. The SMA includes that day's close.
- If 30 of 100 eligible symbols are above their averages, a 40% threshold blocks new entries; 40 of 100 passes.
- **Current fallback:** if there are no eligible symbols, the gate passes. Enabling the gate does not itself add a 200-session preparation requirement; early tests may therefore lack meaningful breadth. Supply sufficient history when relying on this filter.

### Breakeven trigger (R) — `breakeven_r`

- **UI/model default:** `1`. **Range:** 0.1–10.
- Activates at `close >= entry × (1 + stop_pct / 100 × breakeven_r)`.
- With entry ₹100, stop 8% and `breakeven_r = 1`, the trigger is ₹108. At `2`, it is ₹116. The test uses the close, not the day's high.
- Cost-adjusted breakeven is `entry_cost_per_share / ((1 - sell_rate) × (1 - slip))`, so it covers the modeled buy charges and future sell costs. Gaps can still cause a loss.
- This threshold gates both breakeven and the chosen winner management. For example, stop 10% and trigger 3 R require +30%, so a `take_25` run cannot take profit merely upon reaching +25%.
- Trade-report R uses net P&L divided by initial quantity × entry-to-stop distance. That denominator excludes fees, unlike the sizing unit risk.

### Trail below best close (%) — `trail_pct`

- **UI/model default:** `8`. **Range:** > 0 through 50.
- Fallback stop candidate: `best_close_since_entry × (1 - trail_pct / 100)`, applied only after the R trigger, along with breakeven and the existing stop.
- Used if the selected moving average is unavailable, for legacy breakout, and in `take_25` before its gated profit exit is reached.
- It is **not** an extra percentage trail continuously applied alongside an available 50/150-session SMA trail. Lower values tighten the fallback; higher values leave more room.
- The best-close baseline begins at the entry fill. For current-pattern pivot/close entry, entry-day management is skipped as described above.

### Maximum open positions — `max_positions`

- **UI/model default:** `5`. **Range:** 1–50.
- Caps simultaneous holdings. When full, later qualifying candidates are skipped. No existing position is replaced to admit a stronger candidate, and the engine does not buy another lot of an already-held symbol.
- Open-time stop/time exits happen before entries and can release cash and slots. Intraday stop exits happen after the entry pass and cannot fund those entries. A symbol exited that day is not re-entered that day.
- This is not an equal-weight allocation rule or a maximum portfolio-risk percentage.

### Maximum holding sessions — `max_hold_days`

- **UI/model default:** `120`. **Range:** 1–1000.
- Checked at the open: if stored age is at least the limit, the position exits at that open, unless a gap-stop reason takes precedence.
- Age increases during eligible position-management sessions with a candle for that symbol. It does not increase over weekends, missing candles, or the entry-day management skipped for current-pattern pivot/close fills.
- Consequently the calendar duration can exceed this number, and exit occurs at the next available open after the age threshold is accumulated.

### Slippage per side (bps) — `slippage_bps`

- **Current UI/model default:** `10`. **Range:** 0–500.
- Buy fill is `raw_price × (1 + bps / 10000)`; sell fill is `raw_price × (1 - bps / 10000)`.
- At raw ₹100 and 10 bps, buy fill is ₹100.10 and sell fill is ₹99.90, before charges.
- Applies on every side, including stops, time exits, profit exits and end-of-data exits. It also affects sizing and breakeven.
- **Default distinction:** the UI explicitly sets buy/sell charges to zero but does not override slippage, so a fresh comparison run still has 10 bps slippage. For a deliberately cost-free comparison, explicitly set all three cost fields to zero.

### All-in buy charges (bps) — `buy_cost_bps`

- **New UI default:** `0`. **Model/API default:** `10`. **Range:** 0–500.
- Buy charge is `slippage_adjusted_buy_fill × quantity × buy_cost_bps / 10000`.
- Deducted from cash in addition to purchase value; included in sizing and cost-adjusted breakeven. For ₹100,000 executed buy value, 10 bps adds ₹100.
- Enter a combined assumption for applicable fees/taxes. The engine does not itemize or verify historical broker/tax schedules.

### All-in sell charges (bps) — `sell_cost_bps`

- **New UI default:** `0`. **Model/API default:** `10`. **Range:** 0–500.
- Sell charge is `slippage_adjusted_sell_fill × quantity × sell_cost_bps / 10000`.
- Deducted from sale proceeds and net trade P&L. Also affects sizing and breakeven. You can use a different rate from buys.
- Charges are proportional assumptions; minimum ticket charges, fee slabs and changing historical rates are not separately modeled.

### Exploratory-backtest acknowledgement — `acknowledge_limitations`

- **UI/model initial value:** `false`. **Required to run:** `true`.
- The backend rejects a run without acknowledgement. It does not alter fills or filters.
- The recorded limitations include current-constituent survivorship bias, unverified corporate actions/calendar gaps/delisted history, local rather than verified market-wide RS, assumed costs, and no volume participation/circuit-limit/non-fill simulation.

## 5. Defaults at a glance

All four built-in screens currently copy the same filter defaults; the selected pattern determines which ones are active. Saved screens use their stored values, with missing older fields filled from built-in defaults. Adjust & rerun preserves explicit recorded values, including costs and dates.

| Parameter | Fresh UI value | API/model default if omitted |
|---|---|---|
| Screen `name` | `My screen` | Required in screen API |
| Backtest `name` | `Breakout experiment` | `Breakout experiment` |
| `pattern` | `vcp` | Screen API: `vcp`; backtest: legacy `breakout` |
| `base_days` | 15 | 25 |
| `max_depth_pct` | 35 | 30 |
| `volume_multiple` | 1 | 1.5 |
| `sma_days` | 50 | 50 |
| `require_long_trend` | false | false |
| `require_rising_long_trend` | false | false |
| `min_rs_rating` | 0 | 0 |
| `min_turnover` | 50,000,000 | 50,000,000 |
| `vcp_window_days` | 10 | 10 |
| `vcp_volume_multiple` | 0.9 | 0.8 |
| `blue_sky_lookback_days` | 5000 | 5000 |
| `multiyear_base_days` | 260 | 260 |
| `multiyear_max_depth_pct` | 50 | 50 |
| `capital` | 1,000,000 | 1,000,000 |
| `minimum_warmup_sessions` | 50 | 50 |
| Backtest `start`, `end` | Suggested safe window | Required |
| `entry_mode` | pivot | pivot |
| `candidate_rank` | alphabetical | alphabetical |
| `risk_pct` | 1.5 | 1.5 |
| `stop_pct` | 8 | 8 |
| `winner_exit` | trail_50d | trail_50d |
| `skip_weak_markets` | false | false |
| `market_breadth_pct` | 40 | 40 |
| `breakeven_r` | 1 | 1 |
| `trail_pct` | 8 | 8 |
| `max_positions` | 5 | 5 |
| `max_hold_days` | 120 | 120 |
| `slippage_bps` | 10 | 10 |
| `buy_cost_bps` | 0 | 10 |
| `sell_cost_bps` | 0 | 10 |
| `acknowledge_limitations` | false; must check | false; must supply true |

The API accepts only `pattern` and the actual configuration fields, not the UI-only `screen` or `strategy` selectors. Fields with defaults can be omitted by direct API callers; the UI normally submits explicit values. Screen name is required, and backtest dates plus a true acknowledgement must be supplied.

## 6. Practical configuration sequence

1. Select the universe in Settings, request enough daily history before the planned test, refresh the universe and fetch candles.
2. Create/select a screen. Choose its pattern first, then adjust its applicable filters. Save it with a descriptive name if you want to reuse it.
3. Open New backtest and review dates, capital and warmup. The selected screen's filters are copied into this run.
4. Choose entry mode and candidate priority. Configure initial risk/stop, winner management, breadth gate, capacity and holding limit.
5. Enter explicit slippage and both charge assumptions. Check the acknowledgement and run.
6. Inspect exclusions, skipped entries, modeled costs, drawdown and individual trades alongside return. The skipped-entry count includes several causes (RS, breadth, capacity, pivot not reached and insufficient cash), not only cash/position limits.
7. Use Adjust & rerun to vary an assumption while retaining the previous experiment. The application records configuration, universe, report and frozen input data; later data updates do not rewrite old runs. There is no automatic walk-forward optimizer.

## 7. Implementation references

These are repository-relative references so this file remains portable:

- [Configuration models and validation](core/research/config.py)
- [Saved-screen API model and submission endpoints](dashboard/api/main.py)
- [UI fields, built-in presets and new-run defaults](dashboard/web/app.js)
- [Pattern predicates and indicator calculations](strategies/swing_patterns/patterns/signals.py)
- [Warmup, dataset preparation, entries, ranking, breadth and exits](core/research/backtest.py)
- [Position sizing](core/risk/position_sizer.py)
- [Simulated fills, fees and slippage](core/execution/paper.py)

If code changes, update this guide against these sources, especially defaults and entry/exit timing.
