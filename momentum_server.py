#!/usr/bin/env python3
"""
Momentum Scanner - Server voor Render.com
"""

import json
import gzip
import ssl
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Render gebruikt een PORT environment variable
PORT = int(os.environ.get('PORT', 8765))

# SSL uitschakelen voor compatibiliteit
ssl_ctx = ssl._create_unverified_context()

def yahoo_fetch(ticker):
    urls = [
        f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range=1y',
        f'https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range=1y',
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
            self.respond(200, {'status': 'ok', 'message': 'Momentum Scanner Server draait!'})

        elif parsed.path == '/quote':
            ticker = params.get('ticker', [''])[0]
            if not ticker:
                self.respond(400, {'error': 'Geen ticker'}); return
            try:
                data = yahoo_fetch(ticker)
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
                    'closes': closes,
                    'timestamps': timestamps
                })
            except Exception as e:
                self.respond(500, {'error': str(e)})

        elif parsed.path == '/financials':
            ticker = params.get('ticker', [''])[0]
            try:
                url = f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.request.quote(ticker)}?modules=incomeStatementHistory'
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json',
                    'Referer': 'https://finance.yahoo.com/'
                })
                with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
                    raw = resp.read()
                    try: text = gzip.decompress(raw).decode('utf-8')
                    except: text = raw.decode('utf-8')
                    data = json.loads(text)
                stmts = data['quoteSummary']['result'][0]['incomeStatementHistory']['incomeStatementHistory']
                rev, net, years = [], [], []
                from datetime import datetime
                for s in reversed(stmts):
                    years.append(datetime.fromtimestamp(s['endDate']['raw']).year)
                    rev.append((s.get('totalRevenue',{}).get('raw',0) or 0)/1e9)
                    net.append((s.get('netIncome',{}).get('raw',0) or 0)/1e9)
                self.respond(200, {'rev': rev, 'net': net, 'years': years})
            except:
                self.respond(200, {'rev': [], 'net': [], 'years': []})
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
    # Render luistert op 0.0.0.0, niet localhost
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"Momentum Scanner Server draait op port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer gestopt.")
