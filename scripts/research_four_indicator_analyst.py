"""Owner-requested 75% consensus filter: causal coverage audit and explicit hindsight what-if.

Historical analyst publication times are unavailable. Never label these filtered returns
as a point-in-time backtest. Does not change portfolios, orders, configuration or secrets.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import four_indicator_swing as fs
from core.research.analyst_consensus import ConsensusGate, IndianAPIClient, consensus


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')
    temporary.replace(path)


class Collector:
    def __init__(self, client, output, items, max_requests):
        self.client, self.output, self.items = client, output, items
        self.max_requests = max_requests
        self.observations = {}
        for path in (output/'observations').glob('*.json'):
            obs = json.loads(path.read_text(encoding='utf-8'))
            if obs.get('requested_symbol') in items:
                self.observations[obs['requested_symbol']] = obs

    def get(self, symbol):
        if symbol in self.observations:
            return self.observations[symbol]
        if self.client.requests >= self.max_requests:
            raise ValueError('Collection budget reached; no incomplete comparison will be published.')
        obs = self.client.stock(symbol)
        payload = obs['payload']
        if not isinstance(payload, dict):
            obs['unexpected_payload_type'] = type(payload).__name__
            payload = {}
        item = self.items[symbol]
        profile = payload.get('companyProfile') or {} if isinstance(payload, dict) else {}
        isin = profile.get('isInId')
        obs.update(requested_symbol=symbol, expected_isin=item['isin'],
                   identity_verified=bool(isin and isin == item['isin']),
                   provider_isin=isin, provider_symbol=profile.get('exchangeCodeNse'))
        # Keep only the response fields required for reproducibility and identity checks.
        obs['payload'] = {k: payload.get(k) for k in ('companyName','companyProfile','analystView','recosBar')}
        try:
            obs['normalized'] = consensus(obs['payload'])
        except (ValueError, TypeError, KeyError):
            obs['normalized'] = {'status': 'invalid'}
        write(self.output/'observations'/(symbol+'.json'), obs)
        self.observations[symbol] = obs
        if self.client.requests % 10 == 0 or self.client.requests == 1:
            print(f'Indian API: {self.client.requests} requests; {len(self.observations)} observations cached; latest {symbol}.', flush=True)
        return obs

    def gate(self, symbol, signal_date, entry_date):
        self.get(symbol)
        return ConsensusGate(self.observations, threshold_pct=75, allow_hindsight=True)(symbol, signal_date, entry_date)


def html_report(output, plan, results, observations):
    rows = []
    for scope, pair in results.items():
        for variant, value in pair.items():
            m = value['metrics']
            window = plan['windows'][scope]
            label = 'Four indicators' if variant == 'four_indicators' else 'Four + analyst ≥75% (HINDSIGHT)'
            rows.append('<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in (
                window['start']+' to '+window['end'], label, f'{m["return_pct"]:.2f}%', f'{m["max_drawdown_pct"]:.2f}%',
                f'₹{m["final_equity"]:,.2f}', m['trade_count'],len(value['ledger']['positions']),
                f'{m["average_exposure_pct"]:.2f}%', f'₹{m["modeled_fees"]:,.2f}'))+'</tr>')
    coverage = Counter(o.get('normalized', {}).get('status','unknown') for o in observations.values())
    sections = []
    for scope, pair in results.items():
        decisions = pair['75pct_current_consensus_HINDSIGHT']['entry_filter_decisions']
        reasons = Counter(d['evidence']['reason'] for d in decisions)
        sections.append('<h2>'+escape(scope)+' filter decisions</h2><pre>'+escape(json.dumps(reasons,indent=2))+'</pre>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Four indicators + 75% analyst filter: hindsight diagnostic</title>
<style>body{font:15px/1.55 system-ui;margin:32px;color:#193344;max-width:1450px}.warning{padding:18px;background:#fff1c7;border-left:5px solid #bd6900}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ced9df;text-align:right}th{background:#edf2f4}.scroll{overflow:auto}pre{white-space:pre-wrap}</style>
<h1>Four indicators + 75% analyst consensus</h1>
<div class="warning"><strong>HINDSIGHT DIAGNOSTIC — NOT A VALID HISTORICAL ANALYST BACKTEST.</strong>
The filtered rows apply analyst opinions observed on 31 October 2026 to earlier trades. These opinions were unavailable to our system at those entry times. Returns cannot establish that this filter would have helped historically. A causal comparison is unavailable until dated historical observations are obtained or prospective snapshots accumulate.</div>
<p>The four entry conditions, turnover ranking, 10 normal cash slots, next-open entries and Supertrend reversal exits are unchanged. Filtered buys require (Strong Buy + Buy) / all analyst votes ≥75%. Missing coverage, inconsistent counts or an unverified ISIN reject the buy. No minimum analyst count was added. Exit decisions do not depend on analyst opinion.</p>
<p>Both rows start independently with ₹10 lakh and use identical frozen stock inputs, 10 bps slippage per side, detailed Upstox Plus charges throughout, and retained final holdings marked at the final daily close. No orders or production portfolios were changed. Source universe membership, excluded gaps/actions and any provisional daily inputs are inherited from the frozen source portfolios.</p>
<div class="scroll"><table><thead><tr><th>Window</th><th>Variant</th><th>Return</th><th>Max drawdown</th><th>Final equity</th><th>Closed trades</th><th>Open holdings</th><th>Average exposure</th><th>Modeled fees</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div>
<h2>Data provenance and limits</h2><p>Requests were serialized with at least 1.05 seconds after each response before another request. Only candidate stocks encountered with a free portfolio slot were requested, with cached observations reused. Coverage below refers to requested candidates, not the entire universe. Snapshot observation times are stored; broker publication times are unavailable. One/two/three-month relative snapshots were not substituted for exact trade-date opinions.</p><pre>'''+escape(json.dumps(dict(plan=plan,observation_coverage=dict(coverage)),indent=2,default=str))+'''</pre>'''+''.join(sections)+'''<h2>Evidence files</h2><p>comparison.json contains metrics and diagnostics. Each window folder contains the complete baseline and filtered ledgers, equity curves and filter decision audits. observations/ contains dated, identity-checked API responses without credentials.</p></html>'''
    (output/'report.html').write_text(page, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,default=Path('artifacts/four_indicator_paper_comparison_20261030/production_snapshot.json.gz'))
    parser.add_argument('--output',type=Path,default=Path('artifacts/four_indicator_analyst_20261031'))
    parser.add_argument('--key-file',type=Path,required=True)
    parser.add_argument('--max-requests',type=int,default=450)
    args=parser.parse_args()
    snapshot=json.loads(gzip.decompress(args.snapshot.read_bytes()))
    items={i['symbol']:i for record in snapshot['records'].values() for i in record['frozen']['universe']['instruments']}
    client=IndianAPIClient(args.key_file.read_text().strip())
    collector=Collector(client,args.output,items,args.max_requests)
    results={}
    plan=dict(threshold_pct=75,positive_votes=['Strong Buy','Buy'],minimum_analysts=1,
              missing_or_invalid='reject_buy',ranking='turnover',snapshot_sha256=hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
              analyst_mode='current_consensus_hindsight_only',causal_historical_comparison='unavailable',
              rate_limit='One serial request, then at least 1.05 seconds before the next request',windows={})
    try:
        # Recent window first provides a useful complete comparison early in collection.
        for source,scope in [('indicator_all4_20261012','12_october'),('indicator_all4_20251030','one_year')]:
            record=snapshot['records'][source]
            p,f=record['portfolio'],record['frozen']
            cfg=fs.SwingConfig(start=p['start_session'],end=p['ledger']['last_session'],coverage_mode='available_history',
                rule_set='bollinger',capital=1000000,max_positions=10,rsi_threshold=65,bollinger_multiplier=2.5,slippage_bps=10)
            plan['windows'][scope]=dict(start=str(cfg.start),end=str(cfg.end),source=source,stocks=len(f['datasets']),config=cfg.model_dump(mode='json'))
            cache=args.output/(scope+'_signals.json.gz')
            fingerprint=fs.digest(f['datasets'])
            if cache.exists():
                saved=json.loads(gzip.decompress(cache.read_bytes()))
                if saved['fingerprint']!=fingerprint:raise ValueError('Signal cache input changed.')
                signals=saved['signals']
            else:
                print(scope+': computing fixed four-indicator signals.',flush=True)
                signals=fs.features(f['datasets'],lambda s:print(s,flush=True),rsi_threshold=65,bollinger_multiplier=2.5)
                cache.write_bytes(gzip.compress(json.dumps(dict(fingerprint=fingerprint,signals=signals)).encode()))
            kwargs=dict(liquidate=False,instruments=f['universe']['instruments'])
            baseline=fs.simulate(f['datasets'],signals,cfg,fs.RULES[3],**kwargs)
            # Regression parity against the independent established research simulator.
            from scripts.research_four_indicator_selection import SelectionFeatures,Plan,simulate
            independent=simulate(f['datasets'],signals,cfg,SelectionFeatures(f['datasets'],snapshot['index']['bars'],f['universe']['instruments'],cfg),Plan(),liquidate=False)
            if baseline['metrics']!=independent['metrics'] or baseline['curve']!=independent['curve']:
                raise ValueError('Unfiltered baseline failed independent simulator parity.')
            filtered=fs.simulate(f['datasets'],signals,cfg,fs.RULES[3],entry_filter=collector.gate,**kwargs)
            pair={'four_indicators':baseline,'75pct_current_consensus_HINDSIGHT':filtered}
            results[scope]=pair
            for variant,result in pair.items():write(args.output/scope/(variant+'.json'),result)
            print(scope+': baseline '+f'{baseline["metrics"]["return_pct"]:.4f}%; HINDSIGHT filtered '+f'{filtered["metrics"]["return_pct"]:.4f}%.',flush=True)
            summary={s:{v:{'metrics':r['metrics'],'open_positions':len(r['ledger']['positions']),
                          'filter_reasons':dict(Counter(d['evidence']['reason'] for d in r.get('entry_filter_decisions',[])))} for v,r in pairs.items()} for s,pairs in results.items()}
            write(args.output/'comparison.json',dict(plan=plan,results=summary,requests_this_run=client.requests,observations=len(collector.observations),baseline_independent_parity=True))
            html_report(args.output,plan,results,collector.observations)
    finally:
        client.close()
    print('Report: '+str((args.output/'report.html').resolve()),flush=True)


if __name__=='__main__':main()
