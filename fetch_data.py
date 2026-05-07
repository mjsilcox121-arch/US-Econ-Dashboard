#!/usr/bin/env python3
"""
Fetches latest values for all 18 metrics and writes data.json.
Sources:
  - FRED API       : all macro, rates, labor, housing, sentiment
  - Alpha Vantage  : S&P 500 (^GSPC), NASDAQ (^IXIC), Dow (^DJI)
Run daily Mon-Fri on GitHub Actions.
"""

import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone

FRED_KEY = os.environ.get('FRED_API_KEY', '')
AV_KEY   = os.environ.get('AV_API_KEY', '')

FRED_BASE = 'https://api.stlouisfed.org/fred/series/observations'
AV_BASE   = 'https://www.alphavantage.co/query'

MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

def date_label(date_str):
    y, m = date_str.split('-')[:2]
    return MONTHS[int(m)-1] + ' ' + y

def fmt(key, val):
    if key in ('gdp','cpi','corecpi','pce','corepce','retail'):
        return ('+' if val >= 0 else '') + f'{val:.1f}%'
    if key == 'unemp': return f'{val:.1f}%'
    if key in ('ffr','ten'): return f'{val:.2f}%'
    if key == 'nfp':  return ('+' if val >= 0 else '') + f'{int(round(val)):,}K'
    if key in ('mfg','svc','sent'): return f'{val:.1f}'
    if key == 'housing': return f'{val:.3f}M'
    if key == 'trade':
        return ('+$' if val >= 0 else '-$') + f'{abs(round(val))}B'
    if key in ('sp500','nasdaq','dow'): return f'{round(val):,}'
    return str(round(val, 2))

FRED_SERIES = [
    ('gdp',     'A191RL1Q225SBEA', None),
    ('unemp',   'UNRATE',          None),
    ('cpi',     'CPIAUCSL',        'pc1'),
    ('corecpi', 'CPILFESL',        'pc1'),
    ('pce',     'PCEPI',           'pc1'),
    ('corepce', 'PCEPILFE',        'pc1'),
    ('ffr',     'DFF',             None),
    ('ten',     'DGS10',           None),
    ('nfp',     'PAYEMS',          'chg'),
    ('retail',  'RSAFS',           'pch'),
    ('mfg',     'NAPM',            None),
    ('svc',     'NMFCI',           None),
    ('housing', 'HOUST',           None),
    ('trade',   'BOPGSTB',         None),
    ('sent',    'UMCSENT',         None),
]

def fred_fetch(fred_id, units=None):
    params = {'series_id': fred_id, 'api_key': FRED_KEY,
              'file_type': 'json', 'limit': '6', 'sort_order': 'desc'}
    if units:
        params['units'] = units
    url = FRED_BASE + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    obs = [o for o in data.get('observations', [])
           if o['value'] not in ('.', '') and
           o['value'].lstrip('-').replace('.','',1).isdigit()]
    if not obs:
        raise ValueError(f'no data for {fred_id}')
    return obs[0]

AV_EQUITY = [
    ('sp500',  '^GSPC', 'SPY',  10.0),
    ('nasdaq', '^IXIC', None,   None),
    ('dow',    '^DJI',  'DIA',  100.0),
]

FRED_EQUITY_FALLBACK = {
    'sp500':  'SP500',
    'nasdaq': 'NASDAQCOM',
    'dow':    'DJIA',
}

def av_quote(symbol):
    params = {'function': 'GLOBAL_QUOTE', 'symbol': symbol, 'apikey': AV_KEY}
    url = AV_BASE + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    gq = data.get('Global Quote', {})
    price = gq.get('05. price') or gq.get('price')
    if not price:
        raise ValueError(f'no quote for {symbol}')
    return float(price), datetime.now(timezone.utc).strftime('%Y-%m-%d')

def av_fetch(key, primary, fallback, scale):
    try:
        return av_quote(primary)
    except Exception as e:
        print(f'    AV {primary} failed ({e})')
    if fallback and scale:
        try:
            val, date = av_quote(fallback)
            return val * scale, date
        except Exception as e:
            raise ValueError(f'AV fallback {fallback} also failed: {e}')
    raise ValueError(f'AV fetch failed for {key}')

results = {}
errors  = []

for key, fred_id, units in FRED_SERIES:
    try:
        obs = fred_fetch(fred_id, units)
        val = float(obs['value'])
        if key == 'housing':
            val = val / 1000
        results[key] = {
            'value':   round(val, 4),
            'date':    obs['date'],
            'label':   date_label(obs['date']),
            'display': fmt(key, val),
        }
        print(f'  ok  {key:10s} {results[key]["display"]:>12s}  ({results[key]["label"]})')
    except Exception as e:
        errors.append(key)
        print(f'  ERR {key:10s} {e}')

for key, primary, fallback, scale in AV_EQUITY:
    fetched = False
    if AV_KEY:
        try:
            val, date = av_fetch(key, primary, fallback, scale)
            results[key] = {
                'value':   round(val, 2),
                'date':    date,
                'label':   'Today',
                'display': fmt(key, val),
            }
            print(f'  ok  {key:10s} {results[key]["display"]:>12s}  (AV today)')
            fetched = True
        except Exception as e:
            print(f'  AV failed {key}: {e} — trying FRED fallback')
    if not fetched:
        fred_id = FRED_EQUITY_FALLBACK.get(key)
        if fred_id and FRED_KEY:
            try:
                obs = fred_fetch(fred_id)
                val = float(obs['value'])
                results[key] = {
                    'value':   round(val, 2),
                    'date':    obs['date'],
                    'label':   date_label(obs['date']),
                    'display': fmt(key, val),
                }
                print(f'  ok  {key:10s} {results[key]["display"]:>12s}  (FRED fallback)')
                fetched = True
            except Exception as e:
                print(f'  ERR {key} FRED fallback: {e}')
        if not fetched:
            errors.append(key)

output = {
    'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'metrics': results,
    'errors':  errors,
}

with open('data.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f'\nWrote data.json — {len(results)}/18 ok, errors: {errors or "none"}')
