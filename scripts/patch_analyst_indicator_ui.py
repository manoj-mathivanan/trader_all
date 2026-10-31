"""Small UI changes applied equally to local and current production source."""


def app(text):
    text=text.replace('\r\n','\n')
    text=text.replace("'four_indicator_swing','five_indicator_swing'","'four_indicator_swing','five_indicator_swing','four_indicator_analyst'")
    text=text.replace("selectedPaperStrategy==='five_indicator_swing'?state.five_indicator_paper_scenarios:state.four_indicator_paper_scenarios",
        "selectedPaperStrategy==='four_indicator_analyst'?state.analyst_indicator_paper_scenarios:selectedPaperStrategy==='five_indicator_swing'?state.five_indicator_paper_scenarios:state.four_indicator_paper_scenarios")
    text=text.replace("  const five=paper&&state.paper_schemas?.five_indicator_swing?", "  const analyst=paper&&state.paper_schemas?.four_indicator_analyst?[['four_indicator_analyst','Four indicators + analyst consensus']]:[];\n  const five=paper&&state.paper_schemas?.five_indicator_swing?")
    text=text.replace('options.concat(five)','options.concat(five,analyst)')
    text=text.replace("...(state.five_indicator_paper_scenarios||[])","...(state.five_indicator_paper_scenarios||[]),...(state.analyst_indicator_paper_scenarios||[])")
    text=text.replace("strategy==='five_indicator_swing'?'Five indicators · RS126':'All four indicators'", "strategy==='four_indicator_analyst'?'Four indicators · analyst ≥75%':strategy==='five_indicator_swing'?'Five indicators · RS126':'All four indicators'")
    text=text.replace("key==='rule_set'&&selectedPaperStrategy==='five_indicator_swing'", "key==='rule_set'&&['five_indicator_swing','four_indicator_analyst'].includes(selectedPaperStrategy)")
    assert "options.concat(five,analyst)" in text and 'state.analyst_indicator_paper_scenarios' in text
    return text


def indicator(text):
    text=text.replace('\r\n','\n')
    text=text.replace("  const five=selectedPaperStrategy==='five_indicator_swing';", "  const analyst=selectedPaperStrategy==='four_indicator_analyst';\n  const five=selectedPaperStrategy==='five_indicator_swing';")
    text=text.replace("defaults={name:five?", "defaults={name:analyst?'Four indicators + analyst consensus':five?")
    text=text.replace("modal(five?", "modal(analyst?(p?'Configure analyst-filter paper':'Create analyst-filter paper'):five?")
    text=text.replace("<p>${five?'RS126", "<p>${analyst?'All four entry conditions must pass, then Buy + Strong Buy votes must be at least 75% of analyst opinions. Missing or invalid coverage blocks a buy. Forward entries require a snapshot observed before the entry open; exits remain active. ':''}${five?'RS126")
    text=text.replace("k==='rule_set'&&!five?", "k==='rule_set'&&!five&&!analyst?")
    text=text.replace("${five?'Five indicators · RS126 ranking'", "${analyst?'Four indicators · analyst ≥75%':five?'Five indicators · RS126 ranking'")
    text=text.replace("ranking${c.slot_scale<1?", "ranking${c.analyst_buy_threshold_pct?' · analyst Buy + Strong Buy ≥'+c.analyst_buy_threshold_pct+'%':''}${c.slot_scale<1?")
    assert 'Create analyst-filter paper' in text and 'before the entry open' in text
    return text
