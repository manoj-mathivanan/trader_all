"""Transcript-derived research baseline; simulation conventions are explicit."""
from core.strategies.four_indicator import indicators


def specification():
    return dict(
        id='dd_nifty_options_v1', status='research_specification',
        source=dict(video='https://www.youtube.com/watch?v=Fo1lk7t2G7w',
                    rules='08:55–11:25; 20:07–24:59; 28:08–29:06; 50:26–50:49',
                    contracts='38:47–47:05'),
        confirmed=dict(signal_market='NIFTY underlying', timeframes_minutes=[3, 5],
                       supertrend_atr_period=10, supertrend_multiplier=3, rsi_period=14,
                       rsi_call_above=70, rsi_put_below=30, bollinger_period=22,
                       bollinger_multiplier=2, call_filters=['above_supertrend', 'rsi_above_70', 'close_above_r1', 'close_above_upper_band'],
                       put_filters=['below_supertrend', 'rsi_below_30', 'close_below_s1', 'close_below_lower_band'],
                       exit='Underlying candle closes across Supertrend against position.',
                       expiry='Current weekly expiry preferred.'),
        research_assumptions=dict(
            pivot='Traditional pivot from previous completed exchange session HLC; R1=2P-L, S1=2P-H.',
            bar_alignment='09:15 IST session anchor; only complete 3/5 minute bars with every constituent minute.',
            indicators='Continuous across sessions, with at least 100 complete signal bars of warmup.',
            entry='Signal at completed bar end; fill at next one-minute option open plus adverse slippage.',
            strike_selection='Nearest target premium using option close from the last completed minute at signal time; deterministic strike/key tie-break.',
            selection_data='Require complete candidate-chain coverage and positive traded volume in selection minute; skip with reason if unavailable.',
            position='One long call OR long put at a time; one historical contract lot; no leverage.',
            expiry='Nearest listed NIFTY expiry; accept monthly contract in monthly expiry week.',
            capital='Illustrative INR 100000 fixed initial cash; require enough cash for premium and charges.',
            entry_window='Signals from 09:30 inclusive to 15:00 exclusive IST.',
            exit='Next-minute open after completed-bar reversal; scheduled liquidation at 15:20 minute open IST.',
            reentry='After exit require the combined entry condition (all four checks true) to become false at least once before rearming that direction.',
            missing_data='No forward fill, nearest-time substitution, or fictitious liquidation; unresolved position invalidates performance summary.',
            costs='Explicit per-order brokerage, date-specific statutory charges, adverse premium slippage and stress case required before performance claims.',
            special_sessions='Exclude until exchange-specific session schedules are verified.'),
        premium_variants=[dict(id='fixed_250', target='INR 250 per unit'),
                          dict(id='underlying_1pct', target='0.01 * underlying signal close')],
        excluded_from_baseline=['Selling adjustments', 'Candlestick discretion', 'CPR/ADX additions',
                                '25 percent premium stop from the incomplete breakout interview'],
        unresolved=['Exact on-screen pivot setting requires visual confirmation.',
                    'Fee schedule and slippage must be set for the chosen historical period.'],
        validation=['Hand-audit signals and contract choice against timestamped data.',
                    'Check signal invariance when future bars are appended.',
                    'Compare 3-minute and 5-minute variants without selecting on held-out results.',
                    'Reserve last chronological third before tuning.'],
        data_requirements=['Underlying one-minute OHLC and previous-session daily HLC.',
                           'Expired contract catalog, lot sizes, expiry and strike identity.',
                           'Candidate option one-minute OHLCV/OI at selection and through exit.',
                           'Coverage audit for every candidate used to choose nearest premium.'])


def signals(bars, previous_session):
    """Evaluate both directions on already-completed underlying bars.

    Caller supplies verified preceding-session HLC keyed by current session date.
    This function never selects options, sizes positions or assumes fills.
    """
    values = indicators(bars, bollinger_period=22, bollinger_multiplier=2)
    result = []
    for index, (bar, value) in enumerate(zip(bars, values)):
        prior = previous_session.get(bar['date'])
        ready = index >= 99 and prior is not None
        if not ready:
            result.append(dict(ready=False, call=False, put=False, exit_call=False, exit_put=False))
            continue
        pivot = sum(prior[k] for k in ('high', 'low', 'close')) / 3
        r1, s1 = 2*pivot-prior['low'], 2*pivot-prior['high']
        close = bar['close']
        call = value['uptrend'] and close > value['supertrend'] and value['rsi'] > 70 and close > r1 and close > value['upper_band']
        put = not value['uptrend'] and close < value['supertrend'] and value['rsi'] < 30 and close < s1 and close < value['lower_band']
        result.append(dict(ready=True, call=bool(call), put=bool(put),
                           exit_call=close < value['supertrend'], exit_put=close > value['supertrend'],
                           r1=r1, s1=s1, **value))
    return result
