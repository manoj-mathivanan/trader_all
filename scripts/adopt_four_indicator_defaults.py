"""Apply the owner-authorized paper entry settings without replaying its ledger."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research import store, four_indicator_swing as fs
from core.portfolio import manager, four_indicator_paper as paper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--portfolio-id', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', default='artifacts/four_indicator_defaults')
    args = parser.parse_args()
    with store.LOCK:
        before = manager.get(fs.STRATEGY, args.portfolio_id)
        if not before or before['config']['rule_set'] != 'bollinger':
            raise ValueError('Select the existing all-four paper portfolio.')
        if args.apply:
            manager.ensure_idle()
            directory = Path(args.output)
            directory.mkdir(parents=True, exist_ok=True)
            backup = directory / ('before_'+store.now().replace(':','').replace('.','')+'.json')
            backup.write_text(json.dumps(before, indent=2, ensure_ascii=False), encoding='utf-8')
            after = paper.adopt_all_four_defaults(args.portfolio_id)
            for key in ('ledger','metrics','cycles','input_reference','status','replay_through'):
                assert after.get(key) == before.get(key), f'Paper accounting changed: {key}'
            assert all(after['config'][k] == v for k,v in fs.ALL_FOUR_DEFAULTS.items())
            assert after['config']['capital'] == before['config']['capital']
            (directory/'applied.json').write_text(json.dumps(after, indent=2, ensure_ascii=False), encoding='utf-8')
        else:
            after = {**before, 'config':{**before['config'], **fs.ALL_FOUR_DEFAULTS}}
        print(json.dumps(dict(applied=args.apply,portfolio_id=args.portfolio_id,config=after['config'],
                              effective_after_session=before.get('ledger',{}).get('last_session'),
                              retained_holdings=list(before.get('ledger',{}).get('positions',{}))), indent=2))


if __name__ == '__main__':
    main()
