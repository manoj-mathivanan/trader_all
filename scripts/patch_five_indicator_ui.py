"""Apply the five-indicator paper UI additions while preserving other UI edits."""
import re


def app(text):
    text=text.replace('\r\n','\n')
    if 'function isIndicatorStrategy(' in text:
        raise ValueError('Five-indicator UI patch already applied.')
    text=text.replace("'use strict';","'use strict';\nfunction isIndicatorStrategy(id){return ['four_indicator_swing','five_indicator_swing'].includes(id);}",1)
    old="selectedPaperStrategy==='four_indicator_swing' ? (state.four_indicator_paper_scenarios||[])"
    new="isIndicatorStrategy(selectedPaperStrategy) ? ((selectedPaperStrategy==='five_indicator_swing'?state.five_indicator_paper_scenarios:state.four_indicator_paper_scenarios)||[])"
    if text.count(old)!=1:raise ValueError('Unexpected paper selector.')
    text=text.replace(old,new)
    text=text.replace("['swing_patterns','four_indicator_swing']","['swing_patterns','four_indicator_swing','five_indicator_swing']")
    text=text.replace("['scalping','four_indicator_swing']","['scalping','four_indicator_swing','five_indicator_swing']")
    text=text.replace("if(selectedPaperStrategy==='four_indicator_swing')return fourIndicator", "if(isIndicatorStrategy(selectedPaperStrategy))return fourIndicator")
    text=text.replace("...(state.four_indicator_paper_scenarios||[]),", "...(state.four_indicator_paper_scenarios||[]),...(state.five_indicator_paper_scenarios||[]),")
    text=text.replace("strategy==='four_indicator_swing'?", "isIndicatorStrategy(strategy)?")
    text=text.replace(":'All four indicators'):'Scalping'", ":(strategy==='five_indicator_swing'?'Five indicators · RS126':'All four indicators')):'Scalping'")
    match=re.search(r'function strategyOptions\(paper=false\)\{.*?\n\}',text,re.S)
    if not match:raise ValueError('Strategy picker not found.')
    fn=match.group(0).replace("{\n", "{\n  const five=paper&&state.paper_schemas?.five_indicator_swing?[['five_indicator_swing','Five-indicator daily swing']]:[];\n",1)
    fn=fn.replace('if(state.reference_only)return [','if(state.reference_only)return [...five,')
    fn=fn.replace('return options','return options.concat(five)')
    text=text[:match.start()]+fn+text[match.end():]
    text=text.replace("  labels.custom_bps=", "  if(key==='rule_set'&&selectedPaperStrategy==='five_indicator_swing')labels.bollinger='All four entry conditions';\n  labels.custom_bps=",1)
    return text


def indicator(text):
    text=text.replace('\r\n','\n')
    text=text.replace('function fourIndicatorPaperForm(){','function fourIndicatorPaperForm(){\n  const five=selectedPaperStrategy===\'five_indicator_swing\';',1)
    text=text.replace("defaults={name:'Four-indicator paper'", "defaults={name:five?'Five-indicator paper':'Four-indicator paper'",1)
    text=text.replace("modal(p?'Configure indicator paper portfolio':'Create indicator paper portfolio',", "modal(five?(p?'Configure five-indicator paper':'Create five-indicator paper'):(p?'Configure indicator paper portfolio':'Create indicator paper portfolio'),",1)
    text=text.replace('<p>Each portfolio has separate capital.',"<p>${five?'RS126 ranks candidates after all four entry conditions pass; it is not a positive-RS entry gate. Cycles wait for published daily candles; provisional aggregates are deferred. ':''}Each portfolio has separate capital.",1)
    text=text.replace("k==='rule_set'?", "k==='rule_set'&&!five?",1)
    text=text.replace('function fourIndicatorPaperDetail(){','function fourIndicatorPaperDetail(){\n  const five=selectedPaperStrategy===\'five_indicator_swing\';',1)
    text=text.replace("${c.rule_set==='rsi'?", "${five?'Five indicators · RS126 ranking':c.rule_set==='rsi'?",1)
    return text
