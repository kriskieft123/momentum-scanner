#!/usr/bin/env python3
"""
Momentum Scanner - Cloud Server voor Render.com
FIXES v2: SENT_FILE definitie, houd-vast persistentie (/data), news_sent naar /data
"""
import json, gzip, ssl, os, time, threading, urllib.request, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

PORT = int(os.environ.get('PORT', 8765))
TG_TOKEN = os.environ.get('TG_TOKEN', '')
TG_CHAT = os.environ.get('TG_CHAT', '')
DATA_DIR = '/data'
PT_FILE = os.path.join(DATA_DIR, 'papier_handel.json')
SENT_FILE = os.path.join(DATA_DIR, 'sent_signals.json')    # FIX 1: was undefined
HV_FILE = os.path.join(DATA_DIR, 'houd_vast.json')         # FIX 2: persistent
NEWS_SENT_FILE = os.path.join(DATA_DIR, 'news_sent.json')  # FIX 3: /tmp -> /data

ssl_ctx = ssl._create_unverified_context()

WATCHLIST = [
    'ASML.AS','SHELL.AS','INGA.AS','HEIA.AS','ADYEN.AS','PHIA.AS','ASRNL.AS',
    'ABN.AS','AGN.AS','AD.AS','AKZA.AS','BESI.AS','DSFIR.AS','EXO.AS','HLAG.DE',
    'IMCD.AS','KPN.AS','MT.AS','NN.AS','RAND.AS','REN.AS','PRX.AS','UNA.AS',
    'VPK.AS','WKL.AS','NVDA','AAPL','MSFT','GOOG','AMZN','AVGO','META','TSLA',
    'BRK-B','WMT','JPM','LLY','V','ORCL','MA','NFLX','JNJ','COST','BAC',
    'ABBV','XOM','AMD','CRM','PG','GE','KO','PLTR','MCD','IBM','GS','UBER'
]
AEX = ['ASML.AS','SHELL.AS','INGA.AS','HEIA.AS','ADYEN.AS','PHIA.AS','ASRNL.AS',
       'ABN.AS','AGN.AS','AD.AS','AKZA.AS','BESI.AS','DSFIR.AS','EXO.AS','HLAG.DE',
       'IMCD.AS','KPN.AS','MT.AS','NN.AS','RAND.AS','REN.AS','PRX.AS','UNA.AS','VPK.AS','WKL.AS']
PT_BUDGET = 10000
PT_MAX_POSITIES = 25  # verhoogd van 10 naar 25

def load_houd_vast():
    try:
        with open(HV_FILE) as f: return set(json.load(f))
    except: return set()

def save_houd_vast(tickers):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HV_FILE,'w') as f: json.dump(list(tickers),f)
    except Exception as e: print(f'HV save fout: {e}')

HOUD_VAST_TICKERS = load_houd_vast()

def load_pt():
    try:
        with open(PT_FILE) as f: return json.load(f)
    except: return {'active':False,'startDate':None,'startKapitaal':PT_BUDGET,'posities':[],'log':[]}

def save_pt(pt):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PT_FILE,'w') as f: json.dump(pt,f)
    except Exception as e: print(f'PT save fout: {e}')

def load_sent():
    try:
        with open(SENT_FILE) as f: return set(json.load(f))
    except: return set()

def save_sent(sent):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SENT_FILE,'w') as f: json.dump(list(sent),f)
    except: pass

def yahoo_fetch(ticker, rng='1y'):
    urls = [
        f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range={rng}',
        f'https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}?interval=1d&range={rng}',
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://finance.yahoo.com/'})
            with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
                raw = resp.read()
                try: text = gzip.decompress(raw).decode('utf-8')
                except: text = raw.decode('utf-8')
                return json.loads(text)
        except: continue
    raise Exception('Yahoo fetch mislukt')

def bereken_markt_gezondheid(scores):
    """Bepaal markt status op basis van lijst van (ticker, score, d2) tuples"""
    if len(scores) < 10:
        return 'onbekend'
    dalers = sum(1 for _,_,d2 in scores if d2 is not None and d2 < 0)
    breadth_pct = dalers / len(scores) * 100
    gem_score = sum(s for _,s,_ in scores if s is not None) / len(scores)
    gem_d2 = sum(d2 for _,_,d2 in scores if d2 is not None) / max(1, sum(1 for _,_,d2 in scores if d2 is not None))
    snel_dalers = sum(1 for _,_,d2 in scores if d2 is not None and d2 < -3)
    snel_pct = snel_dalers / len(scores) * 100

    if breadth_pct >= 80 and gem_d2 < -1.5 or snel_pct >= 40:
        return 'crash'
    elif breadth_pct >= 70 or gem_d2 < -1:
        return 'waarschuwing'
    elif breadth_pct >= 50:
        return 'voorzichtig'
    return 'gezond'

def get_score_and_price(ticker):
    data = yahoo_fetch(ticker, '1y')
    result = data['chart']['result'][0]
    raw_closes = result['indicators']['quote'][0]['close']
    timestamps = result['timestamp']
    closes = [v for v in raw_closes if v is not None]
    if len(closes) < 10: return None,None,None,None,None,None
    now=closes[-1]; nowTs=timestamps[-1]
    def fc(ts_list,cl_list,ref_ts,days):
        t=ref_ts-days*86400; bi=0; bd=float('inf')
        for i,ts in enumerate(ts_list):
            if cl_list[i] is None: continue
            d=abs(ts-t)
            if d<bd: bd=d; bi=i
        return cl_list[bi]
    w1=fc(timestamps,raw_closes,nowTs,7); m1=fc(timestamps,raw_closes,nowTs,30)
    m3=fc(timestamps,raw_closes,nowTs,90); d2=fc(timestamps,raw_closes,nowTs,2)
    if not w1 or not m1 or not m3: return None,None,None,None,None,None
    score=((now-d2)/d2*100*4 if d2 else 0)+((now-w1)/w1)*100*3+((now-m1)/m1)*100*2+((now-m3)/m3)*100*1
    cutoff=nowTs-7*86400; hist_idx=0
    for i in range(len(timestamps)-1,-1,-1):
        if timestamps[i]<=cutoff: hist_idx=i; break
    hist_score=None
    if hist_idx>10:
        hc=[v for v in raw_closes[:hist_idx+1] if v is not None]
        ht=[timestamps[i] for i in range(hist_idx+1) if raw_closes[i] is not None]
        if len(hc)>=10:
            hn=hc[-1]; hTs=ht[-1]
            hw1=fc(ht,hc,hTs,7); hm1=fc(ht,hc,hTs,30); hm3=fc(ht,hc,hTs,90); hd2=fc(ht,hc,hTs,2)
            if hw1 and hm1 and hm3:
                hist_score=((hn-hd2)/hd2*100*4 if hd2 else 0)+((hn-hw1)/hw1)*100*3+((hn-hm1)/hm1)*100*2+((hn-hm3)/hm3)*100*1
    trend_delta=round(score-hist_score,1) if hist_score is not None else None
    trend_crossed=hist_score is not None and hist_score<100 and score>=100
    week52=closes[-252:] if len(closes)>=252 else closes
    pos52=((now-min(week52))/(max(week52)-min(week52))*100) if max(week52)!=min(week52) else 50
    sma200_now=sum(closes[-200:])/200 if len(closes)>=200 else None
    sma200_old=sum(closes[-230:-30])/200 if len(closes)>=230 else None
    sma200_rising=(sma200_now>sma200_old) if sma200_now and sma200_old else None
    return round(score,1),round(now,4),trend_delta,trend_crossed,round(pos52,1),sma200_rising

def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT: return False
    try:
        url=f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        body=json.dumps({'chat_id':TG_CHAT,'text':msg}).encode('utf-8')
        req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=10,context=ssl_ctx) as resp:
            return json.loads(resp.read()).get('ok',False)
    except Exception as e: print(f'Telegram fout: {e}'); return False

def is_aex_open():
    now=datetime.utcnow()
    if now.weekday()>=5: return False
    t=now.hour*60+now.minute
    return 7*60<=t<=15*60+35

def is_nyse_open():
    now=datetime.utcnow()
    if now.weekday()>=5: return False
    t=now.hour*60+now.minute
    return 13*60+30<=t<=20*60

def is_beurstijd(): return is_aex_open() or is_nyse_open()

def beurs_open_voor(ticker):
    if ticker.endswith('.AS') or ticker.endswith('.DE'): return is_aex_open()
    return is_nyse_open()

def pt_auto_trade(ticker,score,koers,trend_delta,trend_crossed,pos52,sma200_rising,markt_ok=True):
    pt=load_pt()
    if not pt.get('active'): return
    today=datetime.utcnow().strftime('%Y-%m-%d')
    trend_ok=trend_crossed or (trend_delta is not None and trend_delta>0)
    pos52_ok=pos52 is None or pos52>40
    sma200_ok=sma200_rising is None or sma200_rising
    if score>100 and trend_ok and pos52_ok and sma200_ok and markt_ok:  # markt_ok blokkeert bij crash
        al_bezit=any(p['ticker']==ticker and p['open'] for p in pt['posities'])
        if not al_bezit:
            open_pos=len([p for p in pt['posities'] if p['open']])
            if open_pos<PT_MAX_POSITIES:
                bedrag=PT_BUDGET/PT_MAX_POSITIES; aandelen=int(bedrag/koers)
                if aandelen>=1:
                    # Optie 1: auto houd-vast als score >100 + positie sterk
                    auto_hv = score > 100 and (pos52 is None or pos52 > 30) and sma200_rising is not False
                    pos={'ticker':ticker,'aankoopKoers':koers,'aankoopDatum':today,'aandelen':aandelen,'aankoopScore':score,'open':True,'houdVast':auto_hv}
                    pt['posities'].append(pos)
                    pt['log'].insert(0,{'datum':today,'type':'koop','ticker':ticker,'koers':koers,'aandelen':aandelen,'score':score,'houdVast':auto_hv})
                    save_pt(pt)
                    hv_txt = '\n📌 AUTO HOUD-VAST ingesteld' if auto_hv else ''
                    send_telegram(f'🟢 PAPIER KOOP: {ticker}\nScore: {score}\nKoers: {koers}\nAandelen: {aandelen}{hv_txt}')
                    # Sync houd-vast naar bestand
                    if auto_hv:
                        HOUD_VAST_TICKERS.add(ticker)
                        save_houd_vast(HOUD_VAST_TICKERS)
    # Check houd-vast: zowel via globale lijst als via positie-flag
    pos_hv_flags = {p['ticker']:p.get('houdVast',False) for p in pt.get('posities',[]) if p.get('open')}
    if ticker in HOUD_VAST_TICKERS or pos_hv_flags.get(ticker,False):
        for pos in pt['posities']:
            if pos['ticker']==ticker and pos['open']:
                if sma200_rising is not None and not sma200_rising:
                    pos['open']=False; pos['verkoopKoers']=koers; pos['verkoopDatum']=today
                    pos['rendement']=round(((koers-pos['aankoopKoers'])/pos['aankoopKoers'])*100,2)
                    pos['winst']=round((koers-pos['aankoopKoers'])*pos['aandelen'],2)
                    pt['log'].insert(0,{'datum':today,'type':'verkoop','ticker':ticker,'koers':koers,'rendement':pos['rendement'],'winst':pos['winst'],'reden':'SMA200 daalt (houd-vast)'})
                    save_pt(pt)
                    send_telegram(f'⚠️ HOUD-VAST VERKOOP: {ticker}\nSMA200 kantelt\nRendement: {pos["rendement"]}%')
        return
    hard_sell=score<50
    trend_sell=trend_delta is not None and trend_delta<-20 and score<80
    sma200_sell=sma200_rising is not None and not sma200_rising and score<90
    if hard_sell or trend_sell or sma200_sell:
        for pos in pt['posities']:
            if pos['ticker']==ticker and pos['open']:
                pos['open']=False; pos['verkoopKoers']=koers; pos['verkoopDatum']=today
                pos['rendement']=round(((koers-pos['aankoopKoers'])/pos['aankoopKoers'])*100,2)
                pos['winst']=round((koers-pos['aankoopKoers'])*pos['aandelen'],2)
                reden='Score <50' if hard_sell else ('SMA200 daalt' if sma200_sell else f'Trend keert om ({trend_delta})')
                pt['log'].insert(0,{'datum':today,'type':'verkoop','ticker':ticker,'koers':koers,'rendement':pos['rendement'],'winst':pos['winst'],'reden':reden})
                save_pt(pt)
                send_telegram(f'📉 PAPIER VERKOOP: {ticker}\n{reden}\nRendement: {pos["rendement"]}%\nWinst: €{pos["winst"]}')

RED_FLAG_WORDS=['fraud','scandal','bankrupt','recall','resign','fired','lawsuit','investigation','crash','suspended','delisted','warning','loss','decline','miss','downgrade','cut','arrest','probe']
GREEN_FLAG_WORDS=['beats','record','profit','growth','upgrade','buy','strong','surge','rally','partnership','deal','acquisition','dividend','launch']
NEWS_CACHE=[]

def load_news_sent():
    try:
        with open(NEWS_SENT_FILE) as f: return set(json.load(f))
    except: return set()

def save_news_sent(sent):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(NEWS_SENT_FILE,'w') as f: json.dump(list(sent)[-200:],f)
    except: pass

def fetch_news(ticker):
    try:
        url=f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.request.quote(ticker)}&region=US&lang=en-US'
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=10,context=ssl_ctx) as resp:
            text=resp.read().decode('utf-8',errors='ignore')
            titles=re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>',text)
            if not titles: titles=re.findall(r'<title>(.*?)</title>',text)
            return [t.strip() for t in titles[1:6] if t.strip()]
    except: return []

def check_news_for_ticker(ticker,score,in_bezit,news_sent):
    global NEWS_CACHE
    headlines=fetch_news(ticker)
    if not headlines: return news_sent
    today=datetime.utcnow().strftime('%Y-%m-%d')
    for headline in headlines:
        hl_lower=headline.lower(); key=f'news-{ticker}-{headline[:40]}'
        if key in news_sent: continue
        red=any(w in hl_lower for w in RED_FLAG_WORDS)
        green=any(w in hl_lower for w in GREEN_FLAG_WORDS)
        NEWS_CACHE.insert(0,{'ticker':ticker,'headline':headline,'time':datetime.utcnow().strftime('%H:%M'),'date':today,'type':'red' if red else 'green' if green else 'neutral','inBezit':in_bezit,'score':score})
        if len(NEWS_CACHE)>100: NEWS_CACHE=NEWS_CACHE[:100]
        if (red or green) and (in_bezit or score>80):
            icon='⚠️ NIEUWS ALERT' if red else '📰 NIEUWS'
            msg=f'{icon}: {ticker}\n"{headline}"\n{"IN BEZIT!" if in_bezit else f"Score: {score}"}'
            if send_telegram(msg): news_sent.add(key); save_news_sent(news_sent)
        else: news_sent.add(key)
    return news_sent

def news_loop():
    print('Nieuws loop gestart'); news_sent=load_news_sent()
    while True:
        try:
            pt=load_pt(); open_tickers=set(p['ticker'] for p in pt.get('posities',[]) if p.get('open'))
            for ticker in WATCHLIST:
                try: news_sent=check_news_for_ticker(ticker,0,ticker in open_tickers,news_sent); time.sleep(1)
                except Exception as e: print(f'Nieuws fout {ticker}: {e}')
        except Exception as e: print(f'Nieuws loop fout: {e}')
        time.sleep(3600)

def monitor_loop():
    print('Monitor loop gestart'); sent=load_sent()
    markt_status='onbekend'
    scores_deze_ronde=[]
    while True:
        try:
            if is_beurstijd():
                today=datetime.utcnow().strftime('%Y-%m-%d')
                scores_deze_ronde=[]
                for ticker in WATCHLIST:
                    try:
                        score,koers,trend_delta,trend_crossed,pos52,sma200_rising=get_score_and_price(ticker)
                        if score is None: time.sleep(2); continue

                        # Voeg toe aan markt health berekening
                        try:
                            data=yahoo_fetch(ticker,'5d')
                            r=data['chart']['result'][0]
                            cls=[v for v in r['indicators']['quote'][0]['close'] if v is not None]
                            d2=((cls[-1]-cls[-3])/cls[-3]*100) if len(cls)>=3 else None
                            scores_deze_ronde.append((ticker,score,d2))
                        except: scores_deze_ronde.append((ticker,score,None))

                        # Bereken markt gezondheid na elke 10 aandelen
                        if len(scores_deze_ronde)%10==0 and len(scores_deze_ronde)>=10:
                            nieuwe_status=bereken_markt_gezondheid(scores_deze_ronde)
                            if nieuwe_status!=markt_status:
                                print(f'Markt status: {markt_status} → {nieuwe_status}')
                                if nieuwe_status in ['crash','waarschuwing'] and markt_status not in ['crash','waarschuwing']:
                                    dalers=sum(1 for _,_,d2 in scores_deze_ronde if d2 is not None and d2<0)
                                    pct=round(dalers/len(scores_deze_ronde)*100)
                                    send_telegram(f'💀 MARKT ALARM: {nieuwe_status.upper()}\n{pct}% van watchlist daalt\n⛔ Nieuwe aankopen gestopt!')
                                elif nieuwe_status in ['gezond','voorzichtig'] and markt_status in ['crash','waarschuwing']:
                                    send_telegram(f'✅ MARKT HERSTELD: {nieuwe_status}\nNieuwe aankopen weer toegestaan.')
                                markt_status=nieuwe_status

                        beurs_open=beurs_open_voor(ticker)

                        # Blokkeer nieuwe aankopen bij crash of waarschuwing
                        markt_ok = markt_status not in ['crash','waarschuwing']

                        if score>100 and beurs_open:
                            key=f'{ticker}-buy-{today}'
                            if key not in sent:
                                ti='\n⭐ Drempel gekruist!' if trend_crossed else (f'\nTrend: {("+" if trend_delta>0 else "")}{round(trend_delta,1)}' if trend_delta else '')
                                markt_waarsch='' if markt_ok else f'\n⚠️ Markt: {markt_status} — overweeg te wachten'
                                if send_telegram(f'🟢 KOOPSIGNAAL: {ticker}\nScore: {score}\nKoers: {koers}{ti}{markt_waarsch}'): sent.add(key); save_sent(sent)
                        elif score<60 and ticker in AEX and is_aex_open():
                            key=f'{ticker}-sell-{today}'
                            if key not in sent:
                                if send_telegram(f'📉 {"VERKOOPSIGNAAL" if score<50 else "WAARSCHUWING"}: {ticker}\nScore: {score}\nKoers: {koers}'): sent.add(key); save_sent(sent)
                        if beurs_open: pt_auto_trade(ticker,score,koers,trend_delta,trend_crossed,pos52,sma200_rising,markt_ok)
                        time.sleep(3)
                    except Exception as e: print(f'Fout {ticker}: {e}'); time.sleep(3)
            else: print(f'Gesloten: {datetime.utcnow().strftime("%H:%M UTC")}')
        except Exception as e: print(f'Monitor fout: {e}')
        time.sleep(15*60)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args): print(f"[{args[1]}] {args[0]}")
    def do_OPTIONS(self):
        self.send_response(200)
        for h,v in [('Access-Control-Allow-Origin','*'),('Access-Control-Allow-Methods','GET,POST,OPTIONS'),('Access-Control-Allow-Headers','*')]: self.send_header(h,v)
        self.end_headers()
    def do_POST(self):
        global HOUD_VAST_TICKERS
        parsed=urlparse(self.path); length=int(self.headers.get('Content-Length',0)); body=self.rfile.read(length)
        try: data=json.loads(body)
        except: data={}
        if parsed.path=='/houdvast':
            HOUD_VAST_TICKERS=set(data.get('tickers',[])); save_houd_vast(HOUD_VAST_TICKERS)
            self.respond(200,{'status':'ok','tickers':list(HOUD_VAST_TICKERS)})
        else: self.respond(404,{'error':'Niet gevonden'})
    def do_GET(self):
        parsed=urlparse(self.path); params=parse_qs(parsed.query)
        if parsed.path=='/ping': self.respond(200,{'status':'ok','beurstijd':is_beurstijd()})
        elif parsed.path=='/houdvast': self.respond(200,{'tickers':list(HOUD_VAST_TICKERS)})
        elif parsed.path=='/quote':
            ticker=params.get('ticker',[''])[0]
            if not ticker: self.respond(400,{'error':'Geen ticker'}); return
            try:
                data=yahoo_fetch(ticker,'1y'); result=data['chart']['result'][0]
                closes=[v if v is not None else None for v in result['indicators']['quote'][0]['close']]; timestamps=result['timestamp']
                now=None; nowTs=None
                for i in range(len(closes)-1,-1,-1):
                    if closes[i] is not None: now=closes[i]; nowTs=timestamps[i]; break
                if now is None: self.respond(500,{'error':'Geen koersen'}); return
                def fc(days):
                    t=nowTs-days*86400; bi=0; bd=float('inf')
                    for i,ts in enumerate(timestamps):
                        if closes[i] is None: continue
                        d=abs(ts-t)
                        if d<bd: bd=d; bi=i
                    return closes[bi]
                w1=fc(7); m1=fc(30); m3=fc(90); d2=fc(2)
                self.respond(200,{'koers':now,'w':((now-w1)/w1)*100 if w1 else None,'m':((now-m1)/m1)*100 if m1 else None,'m3':((now-m3)/m3)*100 if m3 else None,'d2':((now-d2)/d2)*100 if d2 else None,'closes':closes,'timestamps':timestamps})
            except Exception as e: self.respond(500,{'error':str(e)})
        elif parsed.path=='/financials':
            ticker=params.get('ticker',[''])[0]
            try:
                for url in [f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.request.quote(ticker)}?modules=incomeStatementHistory',f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.request.quote(ticker)}?modules=incomeStatementHistory']:
                    try:
                        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://finance.yahoo.com/'})
                        with urllib.request.urlopen(req,timeout=15,context=ssl_ctx) as resp:
                            raw=resp.read()
                            try: text=gzip.decompress(raw).decode('utf-8')
                            except: text=raw.decode('utf-8')
                            data=json.loads(text)
                            if data.get('quoteSummary',{}).get('result'):
                                stmts=data['quoteSummary']['result'][0]['incomeStatementHistory']['incomeStatementHistory']
                                rev,net,years=[],[],[]
                                for s in reversed(stmts):
                                    years.append(datetime.fromtimestamp(s['endDate']['raw']).year)
                                    rev.append((s.get('totalRevenue',{}).get('raw',0) or 0)/1e9)
                                    net.append((s.get('netIncome',{}).get('raw',0) or 0)/1e9)
                                self.respond(200,{'rev':rev,'net':net,'years':years}); return
                    except: continue
                self.respond(200,{'rev':[],'net':[],'years':[]})
            except: self.respond(200,{'rev':[],'net':[],'years':[]})
        elif parsed.path=='/news': self.respond(200,NEWS_CACHE[:50])
        elif parsed.path=='/backtest':
            ticker=params.get('ticker',[''])[0]
            if not ticker: self.respond(400,{'error':'Geen ticker'}); return
            try:
                data=yahoo_fetch(ticker,'2y'); result=data['chart']['result'][0]
                self.respond(200,{'closes':result['indicators']['quote'][0]['close'],'timestamps':result['timestamp']})
            except Exception as e: self.respond(500,{'error':str(e)})
        elif parsed.path=='/pt':
            pt=load_pt(); pt['pnl']=round(sum(p.get('winst',0) for p in pt['posities'] if not p['open']),2)
            self.respond(200,pt)
        elif parsed.path=='/pt/start':
            pt={'active':True,'startDate':datetime.utcnow().strftime('%Y-%m-%d'),'startKapitaal':PT_BUDGET,'posities':[],'log':[]}
            save_pt(pt); send_telegram('📊 Papier handel gestart!\nBudget: €10.000')
            self.respond(200,{'status':'gestart'})
        elif parsed.path=='/pt/stop':
            pt=load_pt(); pt['active']=False; save_pt(pt); self.respond(200,{'status':'gestopt'})
        else: self.respond(404,{'error':'Niet gevonden'})
    def respond(self,code,data):
        body=json.dumps(data).encode('utf-8')
        self.send_response(code)
        for h,v in [('Content-Type','application/json'),('Content-Length',len(body)),('Access-Control-Allow-Origin','*')]: self.send_header(h,v)
        self.end_headers(); self.wfile.write(body)

if __name__=='__main__':
    os.makedirs(DATA_DIR,exist_ok=True)
    threading.Thread(target=monitor_loop,daemon=True).start()
    threading.Thread(target=news_loop,daemon=True).start()
    server=HTTPServer(('0.0.0.0',PORT),Handler)
    print(f"Server op port {PORT} | Telegram: {'Actief' if TG_TOKEN else 'Uit'} | Houd-vast: {HOUD_VAST_TICKERS}")
    server.serve_forever()
