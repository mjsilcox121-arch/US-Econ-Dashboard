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

import json, os, time, urllib.request, urllib.parse
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

FRED_KEY   = os.environ.get('FRED_API_KEY', '')
AV_KEY     = os.environ.get('AV_API_KEY', '')
GNEWS_KEY  = os.environ.get('GNEWS_API_KEY', '')

FRED_BASE  = 'https://api.stlouisfed.org/fred/series/observations'
AV_BASE    = 'https://www.alphavantage.co/query'
GNEWS_BASE = 'https://gnews.io/api/v4/search'

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


def build_reading(key, dates, vals, label, display, freq):
    """A factual 'Latest Reading' line derived purely from the data.

    No editorializing beyond arithmetic on the FRED/AV series: current value,
    direction vs the prior period, and trailing high/low context.
    """
    period = 'quarter' if freq == 'quarterly' else 'month'
    if len(vals) < 2:
        return f'{label}: {display}.'
    cur, prev = vals[-1], vals[-2]
    prev_disp  = fmt(key, prev)
    prev_label = label_for(key, dates[-2])
    eps = 1e-9
    if abs(cur - prev) < eps:
        change = f'unchanged from {prev_disp} in {prev_label}'
    else:
        change = f'{"up" if cur > prev else "down"} from {prev_disp} in {prev_label}'
    win = vals[-12:] if period == 'month' else vals[-4:]
    ctx = ''
    if len(win) >= 3:
        if cur >= max(win) - eps:
            ctx = f' — its highest reading in {len(win)} {period}s'
        elif cur <= min(win) + eps:
            ctx = f' — its lowest reading in {len(win)} {period}s'
    return f'{label}: {display}, {change}{ctx}.'


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


# One search query per card. Kept specific enough to stay on-topic.
NEWS_QUERIES = {
    'gdp':     'US GDP growth',
    'unemp':   'US unemployment rate',
    'cpi':     'US inflation CPI',
    'corecpi': 'US core inflation',
    'pce':     'US PCE inflation',
    'corepce': 'US core PCE inflation Fed',
    'ffr':     'Federal Reserve interest rate decision',
    'ten':     '10-year Treasury yield',
    'nfp':     'US nonfarm payrolls jobs report',
    'retail':  'US retail sales',
    'mfg':     'ISM manufacturing PMI',
    'svc':     'ISM services PMI',
    'housing': 'US housing starts',
    'trade':   'US trade balance deficit',
    'sent':    'US consumer sentiment',
    'sp500':   'S&P 500 index',
    'nasdaq':  'Nasdaq composite index',
    'dow':     'Dow Jones industrial average',
}

# Prefer well-known outlets; a story from any of these ranks first.
NEWS_PREFERRED = (
    'reuters', 'bloomberg', 'wsj', 'cnbc', 'ap', 'associated press',
    'financial times', 'marketwatch', 'yahoo', 'barron', 'forbes',
    'the new york times', 'washington post', 'business insider',
)


def gnews_fetch(query, max_items=3, days=21):
    """Return up to `max_items` recent, reputable headlines for a query.

    Server-side only (runs in CI). Fetches a batch, drops anything older than
    `days`, ranks preferred outlets first, and truncates. Never fabricates —
    on any failure it returns [] and the card keeps its existing text.
    """
    params = {'q': query, 'lang': 'en', 'country': 'us',
              'max': '10', 'sortby': 'publishedAt', 'apikey': GNEWS_KEY}
    url = GNEWS_BASE + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.load(r)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items = []
    for a in data.get('articles', []):
        title = (a.get('title') or '').strip()
        link  = (a.get('url') or '').strip()
        if not title or not link:
            continue
        pub = a.get('publishedAt', '')
        try:
            pubdt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
        except ValueError:
            continue
        if pubdt < cutoff:
            continue
        src = (a.get('source') or {}).get('name', '')
        items.append({
            'title':  title,
            'url':    link,
            'source': src,
            'date':   pub[:10],
            '_pref':  any(p in src.lower() for p in NEWS_PREFERRED),
        })
    # Preferred outlets first, otherwise keep publish order (already newest-first).
    items.sort(key=lambda x: not x['_pref'])
    for it in items:
        del it['_pref']
    return items[:max_items]


def attach_news(results):
    if not GNEWS_KEY:
        print('  (no GNEWS_API_KEY — skipping news, keeping existing text)')
        return
    for key, query in NEWS_QUERIES.items():
        if key not in results:
            continue
        try:
            items = gnews_fetch(query)
            if items:
                results[key]['news'] = items
                print(f'  news {key:10s} {len(items)} items')
            else:
                print(f'  news {key:10s} none recent')
        except Exception as e:
            print(f'  news ERR {key:10s} {e}')
        time.sleep(1)  # stay well under the free-tier rate limit


def main():
    results = {}
    series  = {}
    errors  = []

    # ── Macro series from FRED (full history + latest) ──────────────────────
    for key, fred_id, units in FRED_SERIES:
        try:
            obs = fred_series(fred_id, units)
            dates = [d for d, _ in obs]
            vals  = [v for _, v in obs]
            if key == 'housing':
                vals = [v / 1000 for v in vals]
            last_date, last_val = dates[-1], vals[-1]
            freq = 'quarterly' if key == 'gdp' else 'monthly'
            label   = label_for(key, last_date)
            display = fmt(key, last_val)
            results[key] = {
                'value':   round(last_val, 4),
                'date':    last_date,
                'label':   label,
                'display': display,
                'reading': build_reading(key, dates, vals, label, display, freq),
            }
            series[key] = {
                'dates':  dates,
                'values': [round(v, 4) for v in vals],
                'freq':   freq,
            }
            print(f'  ok  {key:10s} {results[key]["display"]:>12s}  '
                  f'({results[key]["label"]}, {len(vals)} pts)')
        except Exception as e:
            errors.append(key)
            print(f'  ERR {key:10s} {e}')

    # ── Equities: FRED daily->monthly for the chart, AV quote for the badge ─
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

        # Keep chart end == badge: overwrite (or append) the final monthly point.
        if dates:
            if latest_date[:7] == dates[-1][:7]:
                dates[-1], vals[-1] = latest_date, latest_val
            else:
                dates.append(latest_date)
                vals.append(latest_val)
        else:
            dates, vals = [latest_date], [latest_val]

        label   = month_label(latest_date)
        display = fmt(key, latest_val)
        results[key] = {
            'value':   round(latest_val, 2),
            'date':    latest_date,
            'label':   label,
            'display': display,
            'reading': build_reading(key, dates, vals, label, display, 'monthly'),
        }
        series[key] = {
            'dates':  dates,
            'values': [round(v, 2) for v in vals],
            'freq':   'monthly',
        }
        print(f'  ok  {key:10s} {results[key]["display"]:>12s}  '
              f'({results[key]["label"]}, {len(vals)} pts)')

    # ── Recent news per metric (GNews; no-op without a key) ─────────────────
    attach_news(results)

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


if __name__ == '__main__':
    main()
