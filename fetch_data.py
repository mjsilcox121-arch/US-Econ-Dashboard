#!/usr/bin/env python3
"""Fetches latest values for all 18 metrics from FRED and writes data.json."""

import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone

FRED_KEY = os.environ.get('FRED_API_KEY', '')
BASE = 'https://api.stlouisfed.org/fred/series/observations'

SERIES = [
    # (key,  fred_id,              units,  transform)
    ('gdp',     'A191RL1Q225SBEA',  None,   None),
    ('unemp',   'UNRATE',           None,   None),
    ('cpi',     'CPIAUCSL',         'pc1',  None),
    ('corecpi', 'CPILFESL',         'pc1',  None),
    ('pce',     'PCEPI',            'pc1',  None),
    ('corepce', 'PCEPILFE',         'pc1',  None),
    ('ffr',     'DFF',              None,   None),
    ('ten',     'DGS10',            None,   None),
    ('nfp',     'PAYEMS',           'chg',  None),
    ('retail',  'RSAFS',            'pch',  None),
    ('mfg',     'NAPM',             None,   None),
    ('svc',     'NMFCI',            None,   None),
    ('housing', 'HOUST',            None,   lambda v: v / 1000),
    ('trade',   'BOPGSTB',          None,   None),
    ('sent',    'UMCSENT',          None,   None),
    ('sp500',   'SP500',            None,   None),
    ('nasdaq',  'NASDAQCOM',        None,   None),
    ('dow',     'DJIA',             None,   None),
]

MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

def fmt_label(date_str):
    y, m, _ = date_str.split('-')
    return MONTHS[int(m)-1] + ' ' + y

def fmt_value(key, val):
    if key == 'gdp':     return ('+' if val >= 0 else '') + f'{val:.1f}%'
    if key == 'unemp':   return f'{val:.1f}%'
    if key == 'cpi':     return f'{val:.1f}%'
    if key == 'corecpi': return f'{val:.1f}%'
    if key == 'pce':     return f'{val:.1f}%'
    if key == 'corepce': return f'{val:.1f}%'
    if key == 'ffr':     return f'{val:.2f}%'
    if key == 'ten':     return f'{val:.2f}%'
    if key == 'nfp':     return ('+' if val >= 0 else '') + f'{int(round(val)):,}K'
    if key == 'retail':  return ('+' if val >= 0 else '') + f'{val:.1f}%'
    if key == 'mfg':     return f'{val:.1f}'
    if key == 'svc':     return f'{val:.1f}'
    if key == 'housing': return f'{val:.3f}M'
    if key == 'trade':   return ('+$' if val >= 0 else '-$') + f'{abs(round(val))}B'
    if key == 'sent':    return f'{val:.1f}'
    if key in ('sp500','nasdaq','dow'): return f'{round(val):,}'
    return str(round(val, 2))

def fetch_series(fred_id, units=None):
    params = {
        'series_id': fred_id,
        'api_key': FRED_KEY,
        'file_type': 'json',
        'limit': '6',
        'sort_order': 'desc',
    }
    if units:
        params['units'] = units
    url = BASE + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    obs = [o for o in data.get('observations', [])
           if o['value'] not in ('.', '') and o['value'].replace('-','').replace('.','').isdigit()]
    if not obs:
        raise ValueError(f'No valid observations for {fred_id}')
    return obs[0]   # latest

results = {}
errors = []

for key, fred_id, units, transform in SERIES:
    try:
        obs = fetch_series(fred_id, units)
        val = float(obs['value'])
        if transform:
            val = transform(val)
        results[key] = {
            'value':   round(val, 4),
            'date':    obs['date'],
            'label':   fmt_label(obs['date']),
            'display': fmt_value(key, val),
        }
        print(f'  ✓ {key:10s} {results[key]["display"]:>12s}  ({results[key]["label"]})')
    except Exception as e:
        errors.append(key)
        print(f'  ✗ {key:10s} ERROR: {e}')

output = {
    'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'metrics': results,
    'errors':  errors,
}

with open('data.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f'\nWrote data.json — {len(results)} ok, {len(errors)} failed')
if errors:
    print('Failed:', errors)
