"""Rebuild the frozen HDFCBANK target backtest displayed on the intraday page."""
import json
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research.intraday_target import build_report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--direction', choices=['long', 'short'], default='long')
    direction = parser.parse_args().direction
    report = build_report(direction)
    filename = 'hdfcbank-short-target.json' if direction == 'short' else 'hdfcbank-target.json'
    output = Path(__file__).resolve().parents[1] / 'dashboard' / 'reports' / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('days','curve','assumptions','skipped')}))
