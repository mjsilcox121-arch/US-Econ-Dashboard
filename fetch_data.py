#!/usr/bin/env python3
"""
Fetches latest values AND full history for all 18 metrics and writes data.json.

Output shape:
  {
    "updated": "<UTC ISO8601>",
    "metrics": { key: {value,date,label,display} },   # latest reading (header badge)
    "series":  { key: {dates:[...], values:[...], freq} },  # full history (charts)
    "errors":  [ ...failed keys ]
  }

By construction each series' LAST point equals its badge value, so the chart
always ends on the same number the header shows.

Sources:
  - FRED API       : all macro, rates, labor, housing, sentiment (full history)
  - Alpha Vantage  : S&P 500 / NASDAQ / Dow latest quote (badge freshness)
  - FRED fallback  : SP500 / NASDAQCOM / DJIA daily -> monthly for equity charts
Run daily Mon-Fri on GitHub Actions.
"""

import json, os, urllib.request, urllib.parse
from collections import OrderedDict
from datetime import datetime, timezone

FRED_KEY = os.environ.get('FRED_API_KEY', '')
AV_KEY   = os.environ.get('AV_API_KEY', '')

FRED_BASE = 'https://api.stlouisfed.org/fred/series/observations'
AV_BASE   = 'https://www.alphavantage.co/query'

# History window for the charts. FRED daily equity series only serve ~10y,
# so those charts may start a little later than this.
HISTORY_START = '2015-01-01'

MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']


def month_label(date_str):
    y, m = date_str.split('-')[:2]
    return MONTHS[int(m) - 1] + ' ' + y


def quarter_label(date_str):
    y, m = date_str.split('-')[:2]
    q = (int(m) - 1) // 3 + 1
    return f'Q{q} {y}'


def label_for(key, date_str):
    # GDP is reported quarterly; label it as a quarter, not a month.
    return quarter_label(date_str) if key == 'gdp' else month_label(date_str)


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


def _is_number(s):
    return s not in ('.', '') and s.lstrip('-').replace('.', '', 1).isdigit()


def fred_series(fred_id, units=None, start=HISTORY_START):
    """Return full history as ascending list of (date, float) tuples."""
    params = {'series_id': fred_id, 'api_key': FRED_KEY, 'file_type': 'json',
              'observation_start': start, 'sort_order': 'asc'}
    if units:
        params['units'] = units
    url = FRED_BASE + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    obs = [(o['date'], float(o['value']))
           for o in data.get('observations', [])
           if _is_number(o['value'])]
    if not obs:
        raise ValueError(f'no data for {fred_id}')
    return obs


def fred_monthly_from_daily(fred_id):
    """Downsample a daily FRED series to one point per calendar month (last obs)."""
    obs = fred_series(fred_id)  # ascending
    monthly = OrderedDict()
    for date, val in obs:
        monthly[date[:7]] = (date, val)  # ascending => last wins per month
    dates = [d for d, _ in monthly.values()]
    vals  = [v for _, v in monthly.values()]
    return dates, vals


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
series  = {}
errors  = []

# ── Macro series from FRED (full history + latest) ──────────────────────────
for key, fred_id, units in FRED_SERIES:
    try:
        obs = fred_series(fred_id, units)
        dates = [d for d, _ in obs]
        vals  = [v for _, v in obs]
        if key == 'housing':
            vals = [v / 1000 for v in vals]
        last_date, last_val = dates[-1], vals[-1]
        results[key] = {
            'value':   round(last_val, 4),
            'date':    last_date,
            'label':   label_for(key, last_date),
            'display': fmt(key, last_val),
        }
        series[key] = {
            'dates':  dates,
            'values': [round(v, 4) for v in vals],
            'freq':   'quarterly' if key == 'gdp' else 'monthly',
        }
        print(f'  ok  {key:10s} {results[key]["display"]:>12s}  '
              f'({results[key]["label"]}, {len(vals)} pts)')
    except Exception as e:
        errors.append(key)
        print(f'  ERR {key:10s} {e}')

# ── Equities: FRED daily->monthly for the chart, AV quote for the badge ─────
for key, primary, fallback, scale in AV_EQUITY:
    fred_id = FRED_EQUITY_FALLBACK.get(key)

    dates, vals = [], []
    if fred_id and FRED_KEY:
        try:
            dates, vals = fred_monthly_from_daily(fred_id)
        except Exception as e:
            print(f'  WARN {key} FRED history failed: {e}')

    # Latest badge value: prefer a live Alpha Vantage quote for freshness.
    latest_val, latest_date = None, None
    if AV_KEY:
        try:
            latest_val, latest_date = av_fetch(key, primary, fallback, scale)
        except Exception as e:
            print(f'  AV failed {key}: {e} — using FRED latest')
    if latest_val is None and vals:
        latest_val, latest_date = vals[-1], dates[-1]

    if latest_val is None:
        errors.append(key)
        print(f'  ERR {key:10s} no equity data')
        continue

    # Keep the chart end == badge: overwrite (or append) the final monthly point.
    if dates:
        if latest_date[:7] == dates[-1][:7]:
            dates[-1], vals[-1] = latest_date, latest_val
        else:
            dates.append(latest_date)
            vals.append(latest_val)
    else:
        dates, vals = [latest_date], [latest_val]

    results[key] = {
        'value':   round(latest_val, 2),
        'date':    latest_date,
        'label':   month_label(latest_date),
        'display': fmt(key, latest_val),
    }
    series[key] = {
        'dates':  dates,
        'values': [round(v, 2) for v in vals],
        'freq':   'monthly',
    }
    print(f'  ok  {key:10s} {results[key]["display"]:>12s}  '
          f'({results[key]["label"]}, {len(vals)} pts)')

output = {
    'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'metrics': results,
    'series':  series,
    'errors':  errors,
}

with open('data.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f'\nWrote data.json — {len(results)}/18 metrics ok, '
      f'{len(series)} series, errors: {errors or "none"}')
