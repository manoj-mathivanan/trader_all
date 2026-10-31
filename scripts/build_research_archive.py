"""Package retained intraday/derivatives findings for the read-only website archive."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReportText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'h1', 'h2', 'h3', 'tr', 'li', 'br', 'div'):
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append(' | ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden -= 1
        if tag in ('p', 'h1', 'h2', 'h3', 'tr', 'li', 'div'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def main():
    records = []

    def add(category, title, source, content):
        # Chat links point at laptop-only files; retain labels and archive sources.
        content = re.sub(r'\[([^\]]+)\]\((?:/?C:|file:)[^)]*\)', r'\1 (retained report; see archive sources)', content, flags=re.I)
        records.append(dict(category=category, title=title, source=source, content=content.strip()))

    for chat in json.loads((ROOT / 'artifacts/research-archive-chat-findings.json').read_text(encoding='utf-8')):
        for entry in sorted(chat['entries'], key=lambda e: e['date'] or 0):
            from datetime import datetime, timezone, timedelta
            day = datetime.fromtimestamp(entry['date'], timezone(timedelta(hours=5, minutes=30))).strftime('%d %b %Y')
            add(chat['category'], chat['title'] + ' · ' + day, 'Chat: ' + chat['title'], entry['text'])

    # Earlier investigation documents were consolidated here; keep complete sections.
    architecture = (ROOT / 'architecture.md').read_text(encoding='utf-8')
    anchors = ['scalping-research', 'momentum-research', 'momentum-deep-research',
               'momentum-stronger-rules', 'momentum-indicator-research',
               'momentum-fundamentals-research', 'momentum-reverse-research',
               'nse-intraday-strategy-review', 'intraday-cost-diagnosis', 'intraday-selection-research']
    for anchor in anchors:
        match = re.search(r'<a id="' + anchor + r'"></a>(.*?)(?=\n<a id=|\Z)', architecture, re.S)
        if not match:
            raise ValueError('Missing research section: ' + anchor)
        body = match.group(1).strip()
        add('intraday', body.splitlines()[0].lstrip('# '), 'architecture.md#' + anchor, body)

    paths = [ROOT / 'INTRADAY_SELECTION_RESEARCH.md', ROOT / 'artifacts/intraday_comparison.md', ROOT / 'artifacts/blue_sky_intraday_comparison.md']
    directories = ['candle_context_20261029', 'candle_continuation_20261029', 'candle_diagnostics_20261029',
                   'candle_passive_20261029', 'candle_passive_20261029_v2', 'candle_rejection_20261029',
                   'candle_reversal_20261029', 'four_indicator_5m_year_20261029', 'four_indicator_tightening_20261029',
                   'options_research', 'options_extended_2026', 'option_selling_masterclass', 'option_comparison']
    for directory in directories:
        base = ROOT / 'artifacts' / directory
        paths.extend(p for p in base.rglob('*') if p.suffix in ('.html', '.md', '.txt'))
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        body = path.read_text(encoding='utf-8')
        if path.suffix == '.html':
            parser = ReportText()
            parser.feed(body)
            body = re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(parser.parts))
        source = path.relative_to(ROOT).as_posix()
        category = 'futures' if 'option' in source else 'intraday'
        add(category, source.removeprefix('artifacts/'), source, body)
    payload = dict(as_of='31 October 2026', records=records)
    output = ROOT / 'dashboard/web/research-archive-data.json'
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(records=len(records), bytes=output.stat().st_size,
                          intraday=sum(r['category'] == 'intraday' for r in records),
                          futures=sum(r['category'] == 'futures' for r in records))))


if __name__ == '__main__':
    main()
