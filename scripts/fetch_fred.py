#!/usr/bin/env python3
"""
Fetches the latest value for all 18 FRED series and writes data.json.
Run by GitHub Actions every Monday; the dashboard loads data.json from
the same origin, removing any need for CORS proxies or client-side API calls.
"""

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

FRED_KEY = '9872f28643b310f8622720d19a6dc605'
BASE_URL  = 'https://api.stlouisfed.org/fred/series/observations'

# ── Format helpers ──────────────────────────────────────────────────────────
def pct(d=1):
    return lambda v: f'{v:.{d}f}%'

def signed_pct(d=1):
    return lambda v: ('+' if v >= 0 else '') + f'{v:.{d}f}%'

def nfp(v):
    return ('+' if v >= 0 else '') + f'{round(v):,}K'

def housing(v):
    return f'{v/1000:.3f}M'

def trade(v):
    return ('+$' if v >= 0 else '-$') + f'{abs(round(v))}B'

def integer(v):
    return f'{round(v):,}'

# ── Series config ────────────────────────────────────────────────────────────
SERIES = {
    'gdp':     {'id': 'A191RL1Q225SBEA',                'fmt': signed_pct(1)},
    'unemp':   {'id': 'UNRATE',                          'fmt': pct(1)},
    'cpi':     {'id': 'CPIAUCSL',  'units': 'pc1',       'fmt': pct(1)},
    'corecpi': {'id': 'CPILFESL',  'units': 'pc1',       'fmt': pct(1)},
    'pce':     {'id': 'PCEPI',     'units': 'pc1',       'fmt': pct(1)},
    'corepce': {'id': 'PCEPILFE',  'units': 'pc1',       'fmt': pct(1)},
    'ffr':     {'id': 'DFF',                             'fmt': pct(2)},
    'ten':     {'id': 'DGS10',                           'fmt': pct(2)},
    'nfp':     {'id': 'PAYEMS',    'units': 'chg',       'fmt': nfp},
    'retail':  {'id': 'RSAFS',     'units': 'pch',       'fmt': signed_pct(1)},
    'mfg':     {'id': 'NAPM',                            'fmt': pct(1)},
    'svc':     {'id': 'NMFCI',                           'fmt': pct(1)},
    'housing': {'id': 'HOUST',                           'fmt': housing},
    'trade':   {'id': 'BOPGSTB',                         'fmt': trade},
    'sent':    {'id': 'UMCSENT',                         'fmt': lambda v: f'{v:.1f}'},
    'sp500':   {'id': 'SP500',                           'fmt': integer},
    'nasdaq':  {'id': 'NASDAQCOM',                       'fmt': integer},
    'dow':     {'id': 'DJIA',                            'fmt': integer},
}

# ── Fetch ────────────────────────────────────────────────────────────────────
results, errors = {}, []

for key, cfg in SERIES.items():
    params = {
        'series_id':  cfg['id'],
        'api_key':    FRED_KEY,
        'file_type':  'json',
        'limit':      '6',
        'sort_order': 'desc',
    }
    if 'units' in cfg:
        params['units'] = cfg['units']

    url = BASE_URL + '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'econ-dashboard/1.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())

        obs = next(
            (o for o in data.get('observations', [])
             if o['value'] not in ['.', '']
             and o['value'].lstrip('-').replace('.', '', 1).isdigit()),
            None
        )
        if obs:
            val = float(obs['value'])
            results[key] = {
                'value':   val,
                'date':    obs['date'],
                'display': cfg['fmt'](val),
            }
            print(f'  {key:10s}  {obs["date"]}  {results[key]["display"]}')
        else:
            errors.append(f'{key}: no valid observation')
            print(f'  {key:10s}  !! no valid observation')
    except Exception as e:
        errors.append(f'{key}: {e}')
        print(f'  {key:10s}  !! {e}')

output = {
    'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'metrics':    results,
}

with open('data.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f'\nWrote data.json — {len(results)} metrics OK, {len(errors)} errors')
if errors:
    for e in errors:
        print(f'  ERROR: {e}')
    raise SystemExit(1)
