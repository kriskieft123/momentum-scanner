#!/usr/bin/env python3
"""
Momentum Scanner - Cloud Server voor Render.com
24/7 koersen, Telegram meldingen EN papier handel met disk opslag
"""

import json
import gzip
import ssl
import os
import time
import threading
import urllib.request
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

PORT = int(os.environ.get('PORT', 8765))
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT = os.environ.get('TG_CHAT', '')
DATA_DIR = '/data'
PT_FILE = os.path.join(DATA_DIR, 'papier_handel.json')
FINNHUB_KEY = os.environ.get('FINNHUB_KEY') or 'd7ri6ppr01qahvdne5gd7ri6ppr01qahvdne60'
print(f'Finnhub key: {FINNHUB_KEY[:10]}...')

ssl_ctx = ssl._create_unverified_context()

WATCHLIST = [
    'ASML.AS','SHELL.AS','INGA.AS','HEIA.AS','ADYEN.AS','PHIA.AS','ASRNL.AS',
    'ABN.AS','AGN.AS','AD.AS','AKZA.AS','BESI.AS','DSFIR.AS','EXO.AS','HLAG.DE',
    'IMCD.AS','KPN.AS','MT.AS','NN.AS','RAND.AS','REN.AS','PRX.AS','UNA.AS',
    'VPK.AS','WKL.AS','NVDA','AAPL','MSFT','GOOG','AMZN','AVGO','META','TSLA',
    'BRK-B','WMT','JPM','LLY','V','ORCL','MA','NFLX','JNJ','COST','BAC',
    'ABBV','XOM','AMD','CRM','PG','GE','KO','PLTR','MCD','IBM','GS','UBER'
]

AEX = [
    'ASML.AS','SHELL.AS','INGA.AS','HEIA.AS','ADYEN.AS','PHIA.AS','ASRNL.AS',
    'ABN.AS','AGN.AS','AD.AS','AKZA.AS','BESI.AS','DSFIR.AS','EXO.AS','HLAG.DE',
    'IMCD.AS','KPN.AS','MT.AS','NN.AS','RAND.AS','REN.AS','PRX.AS','UNA.AS',
    'VPK.AS','WKL.AS'
]

PT_BUDGET = 10000

# ── Opslag ────────────────────────────────────────────────────────
def load_pt():
    try:
        with open(PT_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'active': False, 'startDate': None, 'startKapitaal': PT_BUDGET, 'posities': [], 'log': []}

def save_pt(pt):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PT_FILE, 'w') as f:
            json.dump(pt, f)
        print('PT opgeslagen')
    except Exception as e:
        print(f'PT opslaan fout: {e}')

def load_sent():
    try:
        with open(SENT_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()

def save_sent(sent):
    try:
        with open(SENT_FILE, 'w') as f:
            json.dump(list(sent), f)
    except:
        pass

def fetch_finnhub_financials(ticker):
    clean = ticker.replace('.AS','').replace('.DE','').replace('.L','')
    key = FINNHUB_KEY.strip()
    try:
        url = f'https://finnhub.io/api/v1/stock/metric?symbol={urllib.request.quote(clean)}&metric=all&token={key}'
        print(f'Finnhub URL: {url[:80]}')
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            raw = resp.read()
            try: text = gzip.decompress(raw).decode('utf-8')
            except: text = raw.decode('utf-8')
            data = json.loads(text)
        m = data.get('metric', {})
        if not m:
            print(f'Finnhub geen metric data voor {ticker}')
            return None
        rev = m.get('revenuePerShareAnnual', 0)
        net = m.get('netProfitMarginAnnual', 0)
        eps = m.get('epsAnnual', 0)
        pe = m.get('peBasicExclExtraTTM', 0)
        high52 = m.get('52WeekHigh', 0)
        low52 = m.get('52WeekLow', 0)
        print(f'Finnhub OK {ticker}: EPS={eps}, PE={pe}')
        return {
            'rev': [rev] if rev else [],
            'net': [net] if net else [],
            'years': [datetime.utcnow().year],
            'eps': eps, 'pe': pe,
            'high52': high52, 'low52': low52,
            'single': True
        }
    except Exception as e:
        print(f'Finnhub fin fout {ticker}: {e}')
        return None

# ── Yahoo Finance ─────────────────────────────────────────────────
def yahoo_fetch(ticker, rng='1y'):
    urls = [
        f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range={rng}',
        f'https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range={rng}',
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json',
                'Referer': 'https://finance.yahoo.com/'
            })
            with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
                raw = resp.read()
                try: text = gzip.decompress(raw).decode('utf-8')
                except: text = raw.decode('utf-8')
                return json.loads(text)
        except Exception as e:
            continue
    raise Exception('Yahoo fetch mislukt')

def get_score_and_price(ticker):
    data = yahoo_fetch(ticker, '1y')
    result = data['chart']['result'][0]
    raw_closes = result['indicators']['quote'][0]['close']
    timestamps = result['timestamp']
    closes = [v for v in raw_closes if v is not None]
    if len(closes) < 10:
        return None, None, None, None, None, None

    now = closes[-1]
    nowTs = timestamps[-1]

    def fc(ts_list, cl_list, ref_ts, days):
        t = ref_ts - days*86400
        bi = 0; bd = float('inf')
        for i, ts in enumerate(ts_list):
            if cl_list[i] is None: continue
            d = abs(ts-t)
            if d < bd: bd=d; bi=i
        return cl_list[bi]

    w1=fc(timestamps,raw_closes,nowTs,7)
    m1=fc(timestamps,raw_closes,nowTs,30)
    m3=fc(timestamps,raw_closes,nowTs,90)
    d2=fc(timestamps,raw_closes,nowTs,2)
    if not w1 or not m1 or not m3:
        return None, None, None, None, None, None

    score = ((now-d2)/d2*100*4 if d2 else 0) + ((now-w1)/w1)*100*3 + ((now-m1)/m1)*100*2 + ((now-m3)/m3)*100*1

    # Trend: score 7 dagen geleden
    cutoff = nowTs - 7*86400
    hist_idx = 0
    for i in range(len(timestamps)-1, -1, -1):
        if timestamps[i] <= cutoff:
            hist_idx = i; break
    hist_score = None
    if hist_idx > 10:
        hist_closes = [v for v in raw_closes[:hist_idx+1] if v is not None]
        hist_ts = [timestamps[i] for i in range(hist_idx+1) if raw_closes[i] is not None]
        if len(hist_closes) >= 10:
            hn = hist_closes[-1]; hTs = hist_ts[-1]
            hw1=fc(hist_ts,hist_closes,hTs,7)
            hm1=fc(hist_ts,hist_closes,hTs,30)
            hm3=fc(hist_ts,hist_closes,hTs,90)
            hd2=fc(hist_ts,hist_closes,hTs,2)
            if hw1 and hm1 and hm3:
                hist_score = ((hn-hd2)/hd2*100*4 if hd2 else 0) + ((hn-hw1)/hw1)*100*3 + ((hn-hm1)/hm1)*100*2 + ((hn-hm3)/hm3)*100*1

    trend_delta = round(score - hist_score, 1) if hist_score is not None else None
    trend_crossed = hist_score is not None and hist_score < 100 and score >= 100

    # 52-weeks positie
    week52 = closes[-252:] if len(closes) >= 252 else closes
    high52 = max(week52)
    low52 = min(week52)
    pos52 = ((now - low52) / (high52 - low52) * 100) if high52 != low52 else 50

    # SMA200 trend
    sma200_now = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    sma200_old = sum(closes[-230:-30]) / 200 if len(closes) >= 230 else None
    sma200_rising = (sma200_now > sma200_old) if sma200_now and sma200_old else None

    return round(score, 1), round(now, 4), trend_delta, trend_crossed, round(pos52, 1), sma200_rising

# ── Telegram ──────────────────────────────────────────────────────
def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT:
        return False
    try:
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        body = json.dumps({'chat_id': TG_CHAT, 'text': msg}).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            return json.loads(resp.read()).get('ok', False)
    except Exception as e:
        print(f'Telegram fout: {e}')
        return False

# ── Beurstijd ─────────────────────────────────────────────────────
def is_aex_open():
    now = datetime.utcnow()
    if now.weekday() >= 5: return False
    t = now.hour * 60 + now.minute
    return 7*60 <= t <= 15*60+35

def is_nyse_open():
    now = datetime.utcnow()
    if now.weekday() >= 5: return False
    t = now.hour * 60 + now.minute
    return 13*60+30 <= t <= 20*60

def is_beurstijd():
    return is_aex_open() or is_nyse_open()

def beurs_open_voor(ticker):
    if ticker.endswith('.AS') or ticker.endswith('.DE'):
        return is_aex_open()
    return is_nyse_open()

# ── Papier handel ─────────────────────────────────────────────────
def pt_auto_trade(ticker, score, koers, trend_delta, trend_crossed, pos52, sma200_rising):
    pt = load_pt()
    if not pt.get('active'):
        return
    today = datetime.utcnow().strftime('%Y-%m-%d')

    # Koop condities — allemaal groen:
    # 1. Score >100
    # 2. Trend stijgend of drempel gekruist
    # 3. 52-weeks positie >40% (niet op jaarlaag)
    # 4. SMA200 stijgend (als beschikbaar)
    trend_ok = trend_crossed or (trend_delta is not None and trend_delta > 0)
    pos52_ok = pos52 is None or pos52 > 40
    sma200_ok = sma200_rising is None or sma200_rising  # geen data = niet blokkeren

    if score > 100 and trend_ok and pos52_ok and sma200_ok:
        al_bezit = any(p['ticker'] == ticker and p['open'] for p in pt['posities'])
        if not al_bezit:
            open_pos = len([p for p in pt['posities'] if p['open']])
            if open_pos < 10:
                bedrag = PT_BUDGET / 10
                aandelen = int(bedrag / koers)
                if aandelen >= 1:
                    pos = {
                        'ticker': ticker,
                        'aankoopKoers': koers,
                        'aankoopDatum': today,
                        'aandelen': aandelen,
                        'aankoopScore': score,
                        'open': True
                    }
                    pt['posities'].append(pos)
                    pt['log'].insert(0, {'datum': today, 'type': 'koop', 'ticker': ticker, 'koers': koers, 'aandelen': aandelen, 'score': score})
                    save_pt(pt)
                    send_telegram(f'🟢 PAPIER KOOP: {ticker}\nScore: {score}\nKoers: {koers}\nAandelen: {aandelen}')
                    print(f'PT Koop: {ticker} @ {koers}')
    # Verkoop condities:
    # 1. Score <50 (harde verkoopzone)
    # 2. Trend daalt sterk EN score <80
    # 3. SMA200 kantelt naar dalend EN score <90
    trend_sell = trend_delta is not None and trend_delta < -20 and score < 80
    sma200_sell = sma200_rising is not None and not sma200_rising and score < 90
    hard_sell = score < 50

    if hard_sell or trend_sell or sma200_sell:
        for pos in pt['posities']:
            if pos['ticker'] == ticker and pos['open']:
                pos['open'] = False
                pos['verkoopKoers'] = koers
                pos['verkoopDatum'] = today
                pos['rendement'] = round(((koers - pos['aankoopKoers']) / pos['aankoopKoers']) * 100, 2)
                pos['winst'] = round((koers - pos['aankoopKoers']) * pos['aandelen'], 2)
                reden = 'Score in verkoopzone (<50)' if hard_sell else (f'SMA200 kantelt naar dalend (score: {score})' if sma200_sell else f'Momentum keert om (trend: {round(trend_delta,1)}, score: {score})')
                pt['log'].insert(0, {'datum': today, 'type': 'verkoop', 'ticker': ticker, 'koers': koers, 'rendement': pos['rendement'], 'winst': pos['winst'], 'reden': reden})
                save_pt(pt)
                send_telegram(f'📉 PAPIER VERKOOP: {ticker}\n{reden}\nKoers: {koers}\nRendement: {pos["rendement"]}%\nWinst: €{pos["winst"]}')
                print(f'PT Verkoop: {ticker} @ {koers} — {reden}')

# ── Nieuws monitoring ─────────────────────────────────────────────
NEWS_SENT_FILE = '/tmp/news_sent.json'
RED_FLAG_WORDS = ['fraud','scandal','bankrupt','recall','resign','fired','lawsuit','investigation','crash','suspended','delisted','warning','loss','decline','miss','downgrade','cut','arrest','probe']
GREEN_FLAG_WORDS = ['beats','record','profit','growth','upgrade','buy','strong','surge','rally','partnership','deal','acquisition','dividend','launch']

# Mapping ticker naar zoekterm
TICKER_NAMES = {
    'ASML.AS':'ASML','SHELL.AS':'Shell','INGA.AS':'ING','HEIA.AS':'Heineken',
    'ADYEN.AS':'Adyen','PHIA.AS':'Philips','ABN.AS':'ABN AMRO','BESI.AS':'BESI',
    'NVDA':'Nvidia','AAPL':'Apple','MSFT':'Microsoft','GOOG':'Google Alphabet',
    'AMZN':'Amazon','META':'Meta','TSLA':'Tesla','NFLX':'Netflix',
    'AMD':'AMD','PLTR':'Palantir','UBER':'Uber','AVGO':'Broadcom',
    'JPM':'JPMorgan','BAC':'Bank of America','GS':'Goldman Sachs',
    'JNJ':'Johnson Johnson','LLY':'Eli Lilly','ABBV':'AbbVie','PFE':'Pfizer',
    'XOM':'ExxonMobil','V':'Visa','MA':'Mastercard','WMT':'Walmart',
}

def load_news_sent():
    try:
        with open(NEWS_SENT_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()

def save_news_sent(sent):
    try:
        with open(NEWS_SENT_FILE, 'w') as f:
            json.dump(list(sent)[-200:], f)
    except:
        pass

def fetch_news(ticker):
    name = TICKER_NAMES.get(ticker, ticker.replace('.AS','').replace('.DE',''))
    try:
        url = f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.request.quote(ticker)}&region=US&lang=en-US'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            text = resp.read().decode('utf-8', errors='ignore')
        # Parse RSS titels
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', text)
        if not titles:
            titles = re.findall(r'<title>(.*?)</title>', text)
        return [t.strip() for t in titles[1:6] if t.strip()]  # eerste 5 nieuwsberichten
    except:
        return []

NEWS_CACHE = []  # Bewaar laatste nieuws in memory

def check_news_for_ticker(ticker, score, in_bezit, news_sent):
    global NEWS_CACHE
    headlines = fetch_news(ticker)
    if not headlines:
        return news_sent
    today = datetime.utcnow().strftime('%Y-%m-%d')
    for headline in headlines:
        hl_lower = headline.lower()
        key = f'news-{ticker}-{headline[:40]}'
        if key in news_sent:
            continue
        red = any(w in hl_lower for w in RED_FLAG_WORDS)
        green = any(w in hl_lower for w in GREEN_FLAG_WORDS)
        # Voeg toe aan cache
        nieuws_item = {
            'ticker': ticker,
            'headline': headline,
            'time': datetime.utcnow().strftime('%H:%M'),
            'date': today,
            'type': 'red' if red else 'green' if green else 'neutral',
            'inBezit': in_bezit,
            'score': score
        }
        NEWS_CACHE.insert(0, nieuws_item)
        if len(NEWS_CACHE) > 100:
            NEWS_CACHE = NEWS_CACHE[:100]
        if (red or green) and (in_bezit or score > 80):
            icon = '⚠️ NIEUWS ALERT' if red else '📰 NIEUWS'
            bezit_txt = ' · IN BEZIT!' if in_bezit else f' · Score: {score}'
            msg = f'{icon}: {ticker}\n"{headline}"\n{bezit_txt}'
            if send_telegram(msg):
                news_sent.add(key)
                save_news_sent(news_sent)
                print(f'Nieuws verstuurd: {ticker}')
        else:
            news_sent.add(key)
    return news_sent

def news_loop():
    print('Nieuws loop gestart')
    news_sent = load_news_sent()
    while True:
        try:
            if is_beurstijd():
                print(f'Nieuws check: {datetime.utcnow().strftime("%H:%M UTC")}')
                pt = load_pt()
                open_tickers = set(p['ticker'] for p in pt.get('posities', []) if p.get('open'))
                for ticker in WATCHLIST:
                    try:
                        in_bezit = ticker in open_tickers
                        # Haal score op uit cache of skip
                        news_sent = check_news_for_ticker(ticker, 0, in_bezit, news_sent)
                        time.sleep(1)
                    except Exception as e:
                        print(f'Nieuws fout {ticker}: {e}')
                print('Nieuws check klaar')
        except Exception as e:
            print(f'Nieuws loop fout: {e}')
        time.sleep(60 * 60)  # Elk uur


def monitor_loop():
    print('Monitor loop gestart')
    sent = load_sent()
    while True:
        try:
            if is_beurstijd():
                today = datetime.utcnow().strftime('%Y-%m-%d')
                print(f'Controle: {datetime.utcnow().strftime("%H:%M UTC")}')
                for ticker in WATCHLIST:
                    try:
                        score, koers, trend_delta, trend_crossed, pos52, sma200_rising = get_score_and_price(ticker)
                        if score is None:
                            time.sleep(2)
                            continue
                        beurs_open = beurs_open_voor(ticker)
                        # Koopsignaal
                        if score > 100 and beurs_open:
                            key = f'{ticker}-buy-{today}'
                            if key not in sent:
                                trend_info = ''
                                if trend_crossed:
                                    trend_info = '\n⭐ Koopdrempel deze week gekruist!'
                                elif trend_delta is not None:
                                    trend_info = f'\nTrend: {"+" if trend_delta>0 else ""}{round(trend_delta,1)} vs 7d'
                                if send_telegram(f'🟢 KOOPSIGNAAL: {ticker}\nScore: {score}\nKoers: {koers}{trend_info}'):
                                    sent.add(key); save_sent(sent)
                        # Verkoopsignaal alleen AEX
                        elif score < 60 and ticker in AEX and is_aex_open():
                            key = f'{ticker}-sell-{today}'
                            if key not in sent:
                                label = 'VERKOOPSIGNAAL' if score < 50 else 'WAARSCHUWING'
                                if send_telegram(f'📉 {label}: {ticker}\nScore: {score}\nKoers: {koers}'):
                                    sent.add(key); save_sent(sent)
                        # Papier handel
                        if beurs_open:
                            pt_auto_trade(ticker, score, koers, trend_delta, trend_crossed, pos52, sma200_rising)
                        time.sleep(3)
                    except Exception as e:
                        print(f'Fout {ticker}: {e}')
                        time.sleep(3)
                print('Controle klaar')
            else:
                print(f'Beurzen gesloten: {datetime.utcnow().strftime("%H:%M UTC")}')
        except Exception as e:
            print(f'Monitor fout: {e}')
        time.sleep(15 * 60)

# ── HTTP Handler ──────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[Server] {args[0]} {args[1]}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/ping':
            self.respond(200, {'status': 'ok', 'beurstijd': is_beurstijd()})

        elif parsed.path == '/quote':
            ticker = params.get('ticker', [''])[0]
            if not ticker:
                self.respond(400, {'error': 'Geen ticker'}); return
            try:
                data = yahoo_fetch(ticker, '1y')
                result = data['chart']['result'][0]
                closes = [v if v is not None else None for v in result['indicators']['quote'][0]['close']]
                timestamps = result['timestamp']
                now = None; nowTs = None
                for i in range(len(closes)-1, -1, -1):
                    if closes[i] is not None:
                        now = closes[i]; nowTs = timestamps[i]; break
                if now is None:
                    self.respond(500, {'error': 'Geen koersen'}); return
                def fc(days):
                    t = nowTs - days*86400; bi = 0; bd = float('inf')
                    for i, ts in enumerate(timestamps):
                        if closes[i] is None: continue
                        d = abs(ts-t)
                        if d < bd: bd=d; bi=i
                    return closes[bi]
                w1=fc(7); m1=fc(30); m3=fc(90); d2=fc(2)
                self.respond(200, {
                    'koers': now,
                    'w': ((now-w1)/w1)*100 if w1 else None,
                    'm': ((now-m1)/m1)*100 if m1 else None,
                    'm3': ((now-m3)/m3)*100 if m3 else None,
                    'd2': ((now-d2)/d2)*100 if d2 else None,
                    'closes': closes, 'timestamps': timestamps
                })
            except Exception as e:
                self.respond(500, {'error': str(e)})

        elif parsed.path == '/financials':
            ticker = params.get('ticker', [''])[0]
            # Probeer eerst Finnhub
            result = fetch_finnhub_financials(ticker)
            if result and result.get('rev'):
                self.respond(200, result)
            else:
                # Fallback naar Yahoo Finance
                try:
                    urls = [
                        f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.request.quote(ticker)}?modules=incomeStatementHistory',
                        f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.request.quote(ticker)}?modules=incomeStatementHistory',
                    ]
                    data = None
                    for url in urls:
                        try:
                            req = urllib.request.Request(url, headers={
                                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                                'Accept': 'application/json',
                                'Referer': 'https://finance.yahoo.com/',
                            })
                            with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
                                raw = resp.read()
                                try: text = gzip.decompress(raw).decode('utf-8')
                                except: text = raw.decode('utf-8')
                                data = json.loads(text)
                                if data.get('quoteSummary',{}).get('result'):
                                    break
                        except:
                            continue
                    if data:
                        stmts = data['quoteSummary']['result'][0]['incomeStatementHistory']['incomeStatementHistory']
                        rev, net, years = [], [], []
                        for s in reversed(stmts):
                            years.append(datetime.fromtimestamp(s['endDate']['raw']).year)
                            rev.append((s.get('totalRevenue',{}).get('raw',0) or 0)/1e9)
                            net.append((s.get('netIncome',{}).get('raw',0) or 0)/1e9)
                        self.respond(200, {'rev': rev, 'net': net, 'years': years})
                    else:
                        self.respond(200, {'rev': [], 'net': [], 'years': []})
                except:
                    self.respond(200, {'rev': [], 'net': [], 'years': []})

        elif parsed.path == '/news':
            self.respond(200, NEWS_CACHE[:50])

        elif parsed.path == '/pt':
            pt = load_pt()
            geInvesteerd = sum(p['aankoopKoers']*p['aandelen'] for p in pt['posities'] if p['open'])
            geslotenWinst = sum(p.get('winst',0) for p in pt['posities'] if not p['open'])
            pt['pnl'] = round(geslotenWinst, 2)
            self.respond(200, pt)

        elif parsed.path == '/pt/start':
            pt = {'active': True, 'startDate': datetime.utcnow().strftime('%Y-%m-%d'),
                  'startKapitaal': PT_BUDGET, 'posities': [], 'log': []}
            save_pt(pt)
            send_telegram('📊 Papier handel gestart!\nBudget: €10.000\nDe server handelt automatisch tijdens beursuren.')
            self.respond(200, {'status': 'gestart'})

        elif parsed.path == '/pt/stop':
            pt = load_pt()
            pt['active'] = False
            save_pt(pt)
            self.respond(200, {'status': 'gestopt'})

        else:
            self.respond(404, {'error': 'Niet gevonden'})

    def respond(self, code, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    t2 = threading.Thread(target=news_loop, daemon=True)
    t2.start()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"Momentum Scanner Server draait op port {PORT}")
    print(f"Telegram: {'Actief' if TG_TOKEN else 'Niet ingesteld'}")
    print(f"Data dir: {DATA_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer gestopt.")
