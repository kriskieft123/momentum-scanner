#!/usr/bin/env python3
"""
Momentum Scanner - Cloud Server voor Render.com
24/7 koersen, Telegram meldingen EN papier handel
"""

import json
import gzip
import ssl
import os
import time
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

PORT = int(os.environ.get('PORT', 8765))
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT = os.environ.get('TG_CHAT', '')
JSONBIN_KEY = os.environ.get('JSONBIN_KEY', '$2a$10$jqh5XzlIIwgHC86WtPuvN.zwUqrmJJnMTvYB0jyL5Mp88iEICOkze')
JSONBIN_PT_ID = os.environ.get('JSONBIN_PT_ID', '')  # wordt ingesteld na eerste keer
SENT_FILE = '/tmp/sent_signals.json'

ssl_ctx = ssl._create_unverified_context()

def jsonbin_request(method, path, data=None):
    url = f'https://api.jsonbin.io/v3{path}'
    headers = {
        'X-Master-Key': JSONBIN_KEY,
        'Content-Type': 'application/json'
    }
    body = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
        return json.loads(resp.read().decode('utf-8'))

# In-memory opslag als primair
STATE = {'pt': {'active': False, 'startDate': None, 'startKapitaal': PT_BUDGET, 'posities': [], 'log': []}}

def load_pt():
    # Gebruik in-memory als actief
    if STATE["pt"].get('active'):
        return STATE["pt"]
    # Probeer JSONBin als backup
    try:
        if JSONBIN_PT_ID:
            result = jsonbin_request('GET', f'/b/{JSONBIN_PT_ID}/latest')
            data = result.get('record', {})
            if data.get('active'):
                STATE["pt"] = data
                return STATE["pt"]
    except Exception as e:
        print(f'JSONBin load fout: {e}')
    return STATE["pt"]

def save_pt(pt):
    STATE["pt"] = pt  # Altijd in memory opslaan
    # Probeer JSONBin als backup
    try:
        pt['_type'] = 'momentum_pt'
        if not JSONBIN_PT_ID:
            result = jsonbin_request('POST', '/b', pt)
            JSONBIN_PT_ID = result['metadata']['id']
            print(f'JSONBin aangemaakt: {JSONBIN_PT_ID}')
        else:
            jsonbin_request('PUT', f'/b/{JSONBIN_PT_ID}', pt)
    except Exception as e:
        print(f'JSONBin save fout: {e}')
    # Fallback naar bestand
    try:
        with open('/tmp/papier_handel.json', 'w') as f:
            json.dump(pt, f)
    except:
        pass

AEX = [
    'ASML.AS','SHELL.AS','INGA.AS','HEIA.AS','ADYEN.AS','PHIA.AS','ASRNL.AS',
    'ABN.AS','AGN.AS','AD.AS','AKZA.AS','BESI.AS','DSFIR.AS','EXO.AS','HLAG.DE',
    'IMCD.AS','KPN.AS','MT.AS','NN.AS','RAND.AS','REN.AS','PRX.AS','UNA.AS',
    'VPK.AS','WKL.AS'
]

WATCHLIST = [
    'ASML.AS','SHELL.AS','INGA.AS','HEIA.AS','ADYEN.AS','PHIA.AS','ASRNL.AS',
    'ABN.AS','AGN.AS','AD.AS','AKZA.AS','BESI.AS','DSFIR.AS','EXO.AS','HLAG.DE',
    'IMCD.AS','KPN.AS','MT.AS','NN.AS','RAND.AS','REN.AS','PRX.AS','UNA.AS',
    'VPK.AS','WKL.AS','NVDA','AAPL','MSFT','GOOG','AMZN','AVGO','META','TSLA',
    'BRK-B','WMT','JPM','LLY','V','ORCL','MA','NFLX','JNJ','COST','BAC',
    'ABBV','XOM','AMD','CRM','PG','GE','KO','PLTR','MCD','IBM','GS','UBER'
]

PT_BUDGET = 10000

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

def yahoo_fetch(ticker, rng='1y'):
    urls = [
        f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range={rng}',
        f'https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range={rng}',
    ]
    last = 'onbekend'
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
            last = str(e)
            continue
    raise Exception(last)

def get_score_and_price(ticker):
    data = yahoo_fetch(ticker, '1y')
    result = data['chart']['result'][0]
    raw_closes = result['indicators']['quote'][0]['close']
    timestamps = result['timestamp']
    closes = [v for v in raw_closes if v is not None]
    if len(closes) < 10:
        return None, None, None, None
    now = closes[-1]
    nowTs = timestamps[-1]
    def fc(days):
        t = nowTs - days*86400
        bi = 0; bd = float('inf')
        for i, ts in enumerate(timestamps):
            if raw_closes[i] is None: continue
            d = abs(ts-t)
            if d < bd: bd=d; bi=i
        return raw_closes[bi]
    w1=fc(7); m1=fc(30); m3=fc(90)
    if not w1 or not m1 or not m3:
        return None, None, None, None
    score = ((now-w1)/w1)*100*3 + ((now-m1)/m1)*100*2 + ((now-m3)/m3)*100*1
    sma20 = sum(closes[-20:])/min(20,len(closes))
    above_sma = ((now-sma20)/sma20)*100
    good_quality = True  # Kwaliteitscheck uitgeschakeld voor papier handel
    return round(score, 1), round(now, 4), good_quality

def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT:
        return False
    try:
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        body = json.dumps({'chat_id': TG_CHAT, 'text': msg}).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            result = json.loads(resp.read())
            return result.get('ok', False)
    except Exception as e:
        print(f'Telegram fout: {e}')
        return False

def is_aex_open():
    now = datetime.utcnow()
    if now.weekday() >= 5: return False
    tijd = now.hour * 60 + now.minute
    return 7*60 <= tijd <= 15*60+35  # 09:00-17:35 NL = 07:00-15:35 UTC

def is_nyse_open():
    now = datetime.utcnow()
    if now.weekday() >= 5: return False
    tijd = now.hour * 60 + now.minute
    return 13*60+30 <= tijd <= 20*60  # 15:30-22:00 NL = 13:30-20:00 UTC

def is_beurstijd():
    return is_aex_open() or is_nyse_open()

def beurs_voor_ticker(ticker):
    # AEX en Frankfurt
    if ticker.endswith('.AS') or ticker.endswith('.DE') or ticker.endswith('.L'):
        return 'aex'
    return 'nyse'

def pt_auto_trade(ticker, score, koers, good_quality):
    pt = load_pt()
    if not pt['active']:
        return
    today = datetime.utcnow().strftime('%Y-%m-%d')
    if score > 100:
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
    elif score < 50:
        for pos in pt['posities']:
            if pos['ticker'] == ticker and pos['open']:
                pos['open'] = False
                pos['verkoopKoers'] = koers
                pos['verkoopDatum'] = today
                pos['rendement'] = round(((koers - pos['aankoopKoers']) / pos['aankoopKoers']) * 100, 2)
                pos['winst'] = round((koers - pos['aankoopKoers']) * pos['aandelen'], 2)
                pt['log'].insert(0, {'datum': today, 'type': 'verkoop', 'ticker': ticker, 'koers': koers, 'rendement': pos['rendement'], 'winst': pos['winst']})
                save_pt(pt)
                send_telegram(f'📉 PAPIER VERKOOP: {ticker}\nScore: {score}\nKoers: {koers}\nRendement: {pos["rendement"]}%\nWinst: €{pos["winst"]}')
                print(f'PT Verkoop: {ticker} @ {koers}')

def monitor_loop():
    print('Monitor loop gestart')
    sent = load_sent()
    while True:
        try:
            if is_beurstijd():
                print(f'Controle: {datetime.utcnow().strftime("%H:%M UTC")}')
                today = datetime.utcnow().strftime('%Y-%m-%d')
                for ticker in WATCHLIST:
                    try:
                        score, koers, good_quality = get_score_and_price(ticker)
                        if score is None:
                            time.sleep(2)
                            continue
                        # Bepaal of beurs van dit aandeel open is
                        beurs = beurs_voor_ticker(ticker)
                        beurs_open = is_aex_open() if beurs == 'aex' else is_nyse_open()

                        # Koop signalen — alleen als beurs open is
                        if score > 100 and beurs_open:
                            key = f'{ticker}-buy-{today}'
                            if key not in sent:
                                if send_telegram(f'🟢 KOOPSIGNAAL: {ticker}\nScore: {score}\nKoers: {koers}'):
                                    sent.add(key); save_sent(sent)
                        # Verkoop signalen — alleen AEX én alleen als AEX open is
                        elif score < 60 and ticker in AEX and is_aex_open():
                            key = f'{ticker}-sell-{today}'
                            if key not in sent:
                                label = 'VERKOOPSIGNAAL' if score < 50 else 'WAARSCHUWING'
                                if send_telegram(f'📉 {label}: {ticker}\nScore: {score}\nKoers: {koers}'):
                                    sent.add(key); save_sent(sent)
                        # Papier handel
                        pt_auto_trade(ticker, score, koers, good_quality)
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
            try:
                url = f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.request.quote(ticker)}?modules=incomeStatementHistory'
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                    'Referer': 'https://finance.yahoo.com/'
                })
                with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
                    raw = resp.read()
                    try: text = gzip.decompress(raw).decode('utf-8')
                    except: text = raw.decode('utf-8')
                    data = json.loads(text)
                stmts = data['quoteSummary']['result'][0]['incomeStatementHistory']['incomeStatementHistory']
                rev, net, years = [], [], []
                for s in reversed(stmts):
                    years.append(datetime.fromtimestamp(s['endDate']['raw']).year)
                    rev.append((s.get('totalRevenue',{}).get('raw',0) or 0)/1e9)
                    net.append((s.get('netIncome',{}).get('raw',0) or 0)/1e9)
                self.respond(200, {'rev': rev, 'net': net, 'years': years})
            except:
                self.respond(200, {'rev': [], 'net': [], 'years': []})

        elif parsed.path == '/pt':
            pt = load_pt()
            geInvesteerd = sum(p['aankoopKoers']*p['aandelen'] for p in pt['posities'] if p['open'])
            geslotenWinst = sum(p.get('winst',0) for p in pt['posities'] if not p['open'])
            waarde = (PT_BUDGET - geInvesteerd) + geInvesteerd + geslotenWinst
            pt['huidigeWaarde'] = round(waarde, 2)
            pt['pnl'] = round(waarde - PT_BUDGET, 2)
            self.respond(200, pt)

        elif parsed.path == '/pt/start':
            STATE["pt"] = {'active': True, 'startDate': datetime.utcnow().strftime('%Y-%m-%d'),
                  'startKapitaal': PT_BUDGET, 'posities': [], 'log': []}
            save_pt(STATE["pt"])
            send_telegram('📊 Papier handel gestart!\nBudget: €10.000\nDe server handelt automatisch tijdens beursuren.')
            self.respond(200, {'status': 'gestart'})

        elif parsed.path == '/pt/stop':
            STATE["pt"]['active'] = False
            save_pt(STATE["pt"])
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
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"Momentum Scanner Server draait op port {PORT}")
    print(f"Telegram: {'Actief' if TG_TOKEN else 'Niet ingesteld'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer gestopt.")
