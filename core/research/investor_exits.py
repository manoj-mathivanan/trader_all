"""Forward-only profitable exits for managed swing paper positions."""
from copy import deepcopy
from datetime import datetime,time
import math
import httpx
from core.research import store,investor_intelligence as intel
from core.portfolio import manager,paper,midday
from core.execution.paper import PaperBrokerAdapter


def new_adverse_evidence(review,position):
    if not review.get('full_text') or not 0<=intel.cache_age(review)<86400:return False
    by_id={a['id']:a for a in review.get('articles',[])}
    assessment=review.get('thesis_assessment',{})
    citations=list(assessment.get('citations',[])) if assessment.get('status')=='challenged' else []
    for e in review.get('events',[]):
        if e['direction']=='negative' and e['materiality']=='high' and e['evidence_quality'] in ('moderate','strong'):
            citations+=e['citations']
    entry=position.get('entry_at')
    for cite in citations:
        article=by_id.get(cite['article_id'])
        if not article or cite['excerpt'] not in article['text']:continue
        published=datetime.fromisoformat(article['published_at'])
        if entry:
            if published<datetime.fromisoformat(entry):continue
        elif published.astimezone(paper.IST).date().isoformat()<position['entry_date']:continue
        return True
    return False


def transition(portfolio,symbol,quote,review,clock,alert_id):
    """No replay fills: profit is measured at a fresh executable bid, after costs."""
    if portfolio.get('mode')!='paper' or portfolio.get('strategy_name')!='swing_patterns':
        return portfolio,dict(status='unsupported_portfolio')
    if portfolio.get('config',{}).get('investor_news_exits',True) is False:
        return portfolio,dict(status='news_exits_disabled_for_scenario')
    position=portfolio.get('ledger',{}).get('positions',{}).get(symbol)
    if not position:return portfolio,dict(status='already_closed')
    if clock.weekday()>=5 or not time(9,15)<=clock.time().replace(tzinfo=None)<time(15,30):
        return portfolio,dict(status='waiting_market_open')
    if not new_adverse_evidence(review,position):return portfolio,dict(status='no_current_post_entry_discrepancy')
    if not midday.usable_quote(quote,clock):return portfolio,dict(status='waiting_fresh_quote')
    qty=position['quantity']
    if int(quote['depth']['buy'][0]['quantity'])<qty:return portfolio,dict(status='waiting_bid_liquidity')
    cfg=paper.PaperConfig(**portfolio['config']);bid=float(quote['depth']['buy'][0]['price'])
    fill=PaperBrokerAdapter(cfg).fill(bid,qty,'sell',day=clock.date().isoformat())
    proceeds=fill['price']*qty-fill['fees'];profit=proceeds-position['entry_cost']
    if not math.isfinite(profit) or profit<=0:return portfolio,dict(status='not_profitable_after_costs',net_profit=profit)
    result=deepcopy(portfolio);ledger=result['ledger'];day=clock.date().isoformat()
    identity=f'{portfolio["id"]}:investor:{alert_id}:{symbol}:{position["entry_date"]}'
    if any(o.get('id')==identity for o in ledger.get('orders',[])):return portfolio,dict(status='already_executed')
    reason='Investor discrepancy: profitable exit after fees and slippage'
    ledger.setdefault('orders',[]).append(dict(id=identity,symbol=symbol,side='sell',quantity=qty,price=fill['price'],fees=fill['fees'],
        date=day,at=clock.isoformat(),mode='paper',status='simulated',portfolio_id=portfolio['id'],reason=reason,
        alert_id=alert_id,review_id=review['id'],quote=quote,**({'charges':fill['charges']} if 'charges' in fill else {})))
    ledger['cash']+=proceeds;ledger['total_fees']=ledger.get('total_fees',0)+fill['fees'];ledger['total_slippage']=ledger.get('total_slippage',0)+fill['slippage']
    ledger.setdefault('trades',[]).append(dict(symbol=symbol,entry_date=position['entry_date'],entry_at=position.get('entry_at'),
        exit_date=day,exit_at=clock.isoformat(),entry=position['entry'],exit=fill['price'],quantity=qty,pnl=profit,
        r=profit/position['initial_risk'] if position.get('initial_risk',0)>0 else 0,fees=position.get('entry_fee',0)+fill['fees'],
        reason=reason,alert_id=alert_id,review_id=review['id']))
    del ledger['positions'][symbol];ledger.setdefault('marks',{}).pop(symbol,None)
    equity=ledger['cash']+sum(p['quantity']*ledger.get('marks',{}).get(s,p['entry']) for s,p in ledger['positions'].items())
    ledger['peak']=max(ledger.get('peak',cfg.capital),equity);ledger['max_dd']=max(ledger.get('max_dd',0),(ledger['peak']-equity)/ledger['peak']*100)
    # Separate observed intraday valuations from completed-session replay curves.
    ledger.setdefault('investor_valuations',[]).append(dict(at=clock.isoformat(),equity=equity,alert_id=alert_id))
    result['metrics']={**result.get('metrics',{}), 'final_equity':equity,'return_pct':(equity/cfg.capital-1)*100,'max_drawdown_pct':ledger['max_dd'],'trade_count':len(ledger['trades'])}
    result.update(updated_at=store.now())
    result.setdefault('investor_exits',[]).append(dict(at=clock.isoformat(),date=day,symbol=symbol,order_id=identity,review_id=review['id']))
    return result,dict(status='executed',order_id=identity,net_profit=profit,at=clock.isoformat())


def execute(*,log=lambda m:None):
    if not store.read('investor/settings',{}).get('profit_exit_enabled'):return {'exits':0}
    exits=0;clock=paper.local_now()
    for path in sorted((store.DATA/'investor/alerts').glob('*.json')):
        alert=store.read('investor/alerts/'+path.stem)
        if alert.get('status')=='executed':continue
        if alert.get('kind')=='holding_data_review':continue
        review=store.read('investor/reviews/'+alert['review_id'],{})
        outcomes=[]
        for portfolio in manager.list_portfolios('swing_patterns'):
            item=next((i for i in portfolio['universe_snapshot']['instruments'] if i['isin']==alert['isin']),None)
            if not item or item['symbol'] not in portfolio.get('ledger',{}).get('positions',{}):continue
            quote={}
            if clock.weekday()<5 and time(9,15)<=clock.time().replace(tzinfo=None)<time(15,30):
                try:quote=midday.quotes([item]).get(item['symbol'],{})
                except (ValueError,httpx.HTTPError):pass
            with store.LOCK:
                latest=manager.get('swing_patterns',portfolio['id'])
                updated,outcome=transition(latest,item['symbol'],quote,review,clock,alert['id'])
                if outcome['status']=='executed':store.write(manager.key('swing_patterns',portfolio['id']),updated);exits+=1
            outcomes.append(dict(portfolio_id=portfolio['id'],**outcome))
            log(item['symbol']+' investor exit: '+outcome['status'])
        alert['execution']=dict(as_of=store.now(),outcomes=outcomes)
        if outcomes and all(o['status']=='executed' for o in outcomes):alert['status']='executed'
        store.write('investor/alerts/'+alert['id'],alert)
    store.write('investor/execution',dict(as_of=store.now(),exits=exits))
    return dict(exits=exits)
