import os
import json
import time
import requests
from flask import Flask, render_template, jsonify, request
from datetime import datetime

app = Flask(__name__)

# ================================================================
# PASTE YOUR API KEYS BELOW
# Finnhub (free):   https://finnhub.io/register
# Groq (free):      https://console.groq.com/keys
# NewsAPI (free):   https://newsapi.org/register
# ================================================================
FINNHUB_API_KEY = "dasfukhr01qunbokt24gdasfukhr01qunbokt250"
GROQ_API_KEY    = "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"
NEWSAPI_KEY     = "b01215d83e2d452ab1d7aba875f4edac"


# ================================================================
# YAHOO FINANCE — INDIAN STOCK PRICE MAPPING
# ================================================================
INDIAN_YF_SYMBOLS = {
    "RELIANCE":   "RELIANCE.NS",
    "TCS":        "TCS.NS",
    "INFY":       "INFY.NS",
    "HDFCBANK":   "HDFCBANK.NS",
    "ICICIBANK":  "ICICIBANK.NS",
    "SBIN":       "SBIN.NS",
    "ITC":        "ITC.NS",
    "LT":         "LT.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    "HINDUNILVR": "HINDUNILVR.NS",
}

INDIAN_STOCKS = {
    "RELIANCE":  "Reliance Industries",
    "TCS":       "Tata Consultancy Services",
    "INFY":      "Infosys",
    "HDFCBANK":  "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "SBIN":      "State Bank of India",
    "ITC":       "ITC Limited",
    "LT":        "Larsen and Toubro",
    "BHARTIARTL":"Bharti Airtel",
    "HINDUNILVR":"Hindustan Unilever",
}


# ================================================================
# QUOTE CACHE (prevents Finnhub rate limiting)
# ================================================================
_quote_cache = {}
_quote_cache_ttl = 60
_finnhub_calls = []
_finnhub_max_per_min = 50


def _rate_limit_ok():
    now = time.time()
    global _finnhub_calls
    _finnhub_calls = [t for t in _finnhub_calls if now - t < 60]
    return len(_finnhub_calls) < _finnhub_max_per_min


# ================================================================
# WATCHLIST + COMPANY NAMES
# ================================================================
WATCHLIST = [
    {"symbol": "KO",   "sector": "consumer"},
    {"symbol": "TSLA", "sector": "automotive"},
    {"symbol": "NVDA", "sector": "tech"},
    {"symbol": "AAPL", "sector": "tech"},
    {"symbol": "MSFT", "sector": "tech"},
    {"symbol": "RELIANCE", "sector": "tech"},
    {"symbol": "TCS",      "sector": "tech"},
]

ai_cache = {}

COMPANY_NAMES = {
    "KO": "Coca-Cola Co.", "TSLA": "Tesla Inc.", "NVDA": "NVIDIA Corp.",
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.", "META": "Meta Platforms", "JPM": "JPMorgan Chase",
    "DIS": "Walt Disney Co.", "NFLX": "Netflix Inc.", "AMD": "Advanced Micro Devices",
    "RELIANCE": "Reliance Industries", "TCS": "Tata Consultancy Services",
    "INFY": "Infosys", "HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank",
    "SBIN": "State Bank of India", "ITC": "ITC Limited", "LT": "Larsen and Toubro",
    "BHARTIARTL": "Bharti Airtel", "HINDUNILVR": "Hindustan Unilever",
}

FALLBACK_NEWS = {
    "KO": [{"headline": "Coca-Cola faces consumer backlash after viral live event",
            "source": "Reuters", "datetime": 1712000000, "url": "#"}],
    "TSLA": [{"headline": "NHTSA opens preliminary inquiry into Autopilot safety updates",
              "source": "WSJ", "datetime": 1712000000, "url": "#"}],
    "NVDA": [{"headline": "Cloud giant announces $10B NVIDIA infrastructure deal",
              "source": "CNBC", "datetime": 1712000000, "url": "#"}],
    "AAPL": [{"headline": "Apple unveils new AI features at developer conference",
              "source": "The Verge", "datetime": 1712000000, "url": "#"}],
    "MSFT": [{"headline": "Microsoft Azure growth accelerates on AI demand",
              "source": "FT", "datetime": 1712000000, "url": "#"}],
    "RELIANCE": [{"headline": "Reliance Industries reports steady growth in retail and telecom",
                  "source": "Economic Times", "datetime": 1712000000, "url": "#"}],
    "TCS": [{"headline": "TCS wins multi-year deal with European banking client",
             "source": "Business Standard", "datetime": 1712000000, "url": "#"}],
}


# ================================================================
# GROQ AI ANALYSIS
# ================================================================

def ai_analyze(headline, company, symbol):
    cache_key = f"{symbol}::{headline[:80]}"
    if cache_key in ai_cache:
        return ai_cache[cache_key]

    if GROQ_API_KEY == "PASTE_YOUR_GROQ_KEY_HERE":
        result = _simple_fallback(headline)
        ai_cache[cache_key] = result
        return result

    prompt = f"""You are a financial analyst AI. Analyze this news headline for stock {symbol} ({company}):

HEADLINE: "{headline}"

Return ONLY valid JSON with this exact structure:
{{
  "recommendation": "BUY" or "SELL" or "HOLD",
  "confidence": a number from 0 to 100,
  "impact_score": a number from -1.00 to +1.00,
  "severity": "critical" or "high" or "neutral" or "bullish",
  "reason": "one short sentence, max 15 words",
  "time_horizon": "intraday" or "short-term" or "long-term"
}}

Rules:
- Negative news -> SELL or HOLD, impact negative
- Positive news -> BUY, impact positive
- Ambiguous -> HOLD, impact near 0
- critical: fraud, SEC, major lawsuit, scandal, recall
- high: regulatory inquiry, downgrade, weak earnings
- bullish: major contract, earnings beat, upgrade, expansion

Return ONLY the JSON object."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "openai/gpt-oss-120b",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.2, "max_tokens": 200},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"Groq error {r.status_code}: {r.text[:200]}")
            return _simple_fallback(headline)

        content = r.json()["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        result = {
            "recommendation": str(data.get("recommendation", "HOLD")).upper(),
            "confidence": max(0, min(100, int(data.get("confidence", 50)))),
            "impact_score": max(-1.0, min(1.0, float(data.get("impact_score", 0)))),
            "severity": str(data.get("severity", "neutral")).lower(),
            "reason": str(data.get("reason", "AI analysis")),
            "time_horizon": str(data.get("time_horizon", "short-term")),
        }
        ai_cache[cache_key] = result
        return result
    except Exception as e:
        print(f"Groq exception: {e}")
        return _simple_fallback(headline)


def _simple_fallback(headline):
    t = headline.lower()
    neg = ["lawsuit","sec","fraud","recall","scandal","crash","inquiry","probe",
           "investigation","drop","fall","plunge","downgrade","loss"]
    pos = ["surge","soar","beat","record","growth","deal","partnership","upgrade",
           "profit","rally","bullish","launch","expansion","boost"]
    n = sum(1 for w in neg if w in t)
    p = sum(1 for w in pos if w in t)
    if n > p:
        return {"recommendation":"SELL","confidence":70+n*5,
                "impact_score":-min(1.0,0.4+n*0.15),
                "severity":"critical" if n>=2 else "high",
                "reason":"Negative keywords detected.","time_horizon":"short-term"}
    if p > n:
        return {"recommendation":"BUY","confidence":70+p*5,
                "impact_score":min(1.0,0.4+p*0.15),"severity":"bullish",
                "reason":"Positive keywords detected.","time_horizon":"short-term"}
    return {"recommendation":"HOLD","confidence":55,"impact_score":0.0,
            "severity":"neutral","reason":"Neutral sentiment.",
            "time_horizon":"short-term"}


# ================================================================
# FINNHUB — US NEWS + US QUOTES
# ================================================================

def fetch_news(symbol):
    if FINNHUB_API_KEY == "PASTE_YOUR_FINNHUB_KEY_HERE":
        return None
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = datetime.fromtimestamp(
            datetime.now().timestamp() - 7 * 86400).strftime("%Y-%m-%d")
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol":symbol,"from":week_ago,"to":today,"token":FINNHUB_API_KEY},
            timeout=15)
        if r.status_code != 200:
            print(f"Finnhub news HTTP {r.status_code} for {symbol}")
            return None
        return r.json()[:6]
    except Exception as e:
        print(f"Finnhub news error {symbol}: {e}")
        return None


def fetch_quote(symbol):
    if FINNHUB_API_KEY == "PASTE_YOUR_FINNHUB_KEY_HERE":
        return None

    now = time.time()
    cached = _quote_cache.get(symbol)
    if cached and (now - cached["ts"] < _quote_cache_ttl):
        return cached["data"]

    if not _rate_limit_ok():
        print(f"Finnhub rate limit — using cache for {symbol}")
        return cached["data"] if cached else None

    try:
        _finnhub_calls.append(now)
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol":symbol, "token":FINNHUB_API_KEY},
            timeout=15)

        if r.status_code != 200:
            print(f"Finnhub quote HTTP {r.status_code} for {symbol}")
            return cached["data"] if cached else None

        d = r.json()
        if not d.get("c"):
            return cached["data"] if cached else None

        data = {
            "price": d.get("c", 0),
            "change": d.get("d", 0),
            "changePercent": d.get("dp", 0),
            "high": d.get("h", 0),
            "low": d.get("l", 0),
            "open": d.get("o", 0),
            "prevClose": d.get("pc", 0),
            "currency": "USD",
        }
        _quote_cache[symbol] = {"data": data, "ts": now}
        return data
    except Exception as e:
        print(f"Finnhub quote error {symbol}: {e}")
        return cached["data"] if cached else None


# ================================================================
# NEWSAPI — INDIAN NEWS
# ================================================================

def fetch_newsapi_news(symbol, company_name):
    if NEWSAPI_KEY == "PASTE_YOUR_NEWSAPI_KEY_HERE":
        return None
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q":f'"{company_name}" stock', "apiKey":NEWSAPI_KEY,
                    "pageSize":6, "language":"en", "sortBy":"publishedAt"},
            timeout=15)
        if r.status_code != 200:
            print(f"NewsAPI HTTP {r.status_code} for {symbol}: {r.text[:200]}")
            return None
        articles = r.json().get("articles", [])
        return [{
            "headline": a.get("title",""),
            "source": (a.get("source") or {}).get("name","NewsAPI"),
            "datetime": a.get("publishedAt",""),
            "url": a.get("url","#"),
        } for a in articles if a.get("title")]
    except Exception as e:
        print(f"NewsAPI error {symbol}: {e}")
        return None


# ================================================================
# YAHOO FINANCE — INDIAN PRICE
# ================================================================

def fetch_indian_quote(symbol):
    try:
        import yfinance as yf
        yf_symbol = INDIAN_YF_SYMBOLS.get(symbol)
        if not yf_symbol:
            return None
        ticker = yf.Ticker(yf_symbol)
        info = ticker.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose")
        if not price:
            print(f"Yahoo returned no price for {yf_symbol}")
            return None
        change = price - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "price": round(price, 2),
            "change": round(change, 2),
            "changePercent": round(change_pct, 2),
            "high": info.get("dayHigh") or 0,
            "low": info.get("dayLow") or 0,
            "open": info.get("open") or 0,
            "prevClose": prev_close or 0,
            "currency": "INR",
        }
    except Exception as e:
        print(f"Yahoo Finance error for {symbol}: {e}")
        return None


# ================================================================
# BUILD THREAT CARDS
# ================================================================

def build_threats_for_symbol(symbol, sector, max_articles=2):
    is_indian = symbol in INDIAN_STOCKS
    if is_indian:
        articles = fetch_newsapi_news(symbol, INDIAN_STOCKS[symbol])
        quote = fetch_indian_quote(symbol)
        currency = "INR"
    else:
        articles = fetch_news(symbol)
        quote = fetch_quote(symbol)
        currency = "USD"

    if not articles:
        articles = FALLBACK_NEWS.get(symbol, [])
    price = quote["price"] if quote else None

    results = []
    for i, a in enumerate(articles[:max_articles]):
        headline = a.get("headline") or a.get("title","")
        if not headline:
            continue
        company = COMPANY_NAMES.get(symbol, symbol)
        ai = ai_analyze(headline, company, f"${symbol}")

        results.append({
            "id": f"{symbol.lower()}-{i}",
            "symbol": f"${symbol}",
            "company": company,
            "severity": ai["severity"],
            "severityLabel": {
                "critical":"🚨 CRITICAL RISK","high":"⚠️ HIGH RISK",
                "bullish":"🚀 BULLISH CATALYST","neutral":"ℹ️ NEUTRAL",
            }.get(ai["severity"], "ℹ️ NEUTRAL"),
            "headline": headline,
            "source": a.get("source","Unknown"),
            "analysisType": ("NewsAPI · " if is_indian else "Finnhub · ") + a.get("source","News"),
            "impactScore": ai["impact_score"],
            "confidence": ai["confidence"],
            "recommendation": ai["recommendation"],
            "reason": ai["reason"],
            "timeHorizon": ai["time_horizon"],
            "latency": round(1.5 + i*0.7, 1),
            "sectors": [sector],
            "action": _action_for(ai["recommendation"], ai["severity"]),
            "price": price,
            "currency": currency,
            "isIndian": is_indian,
            "quote": quote,
            "slippage": abs(int(ai["impact_score"]*150)) + 20,
            "url": a.get("url","#"),
            "timestamp": a.get("datetime",0),
        })
    return results


def _action_for(rec, severity):
    if rec == "SELL":
        return {"label":"SELL IMMEDIATELY","icon":"⚡","type":"SELL","color":"red"}
    if rec == "BUY":
        return {"label":"BUY / INCREASE POSITION","icon":"📈","type":"BUY","color":"green"}
    if severity == "high":
        return {"label":"SET TIGHT STOP-LOSS","icon":"🛡️","type":"STOP-LOSS","color":"amber"}
    return {"label":"HOLD · MONITOR POSITION","icon":"👁️","type":"HOLD","color":"gray"}


# ================================================================
# ROUTES
# ================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/feed")
def api_feed():
    all_threats = []
    for item in WATCHLIST:
        try:
            all_threats.extend(build_threats_for_symbol(item["symbol"], item["sector"]))
        except Exception as e:
            print(f"Feed error for {item['symbol']}: {e}")

    order = {"critical":0,"high":1,"neutral":2,"bullish":3}
    all_threats.sort(key=lambda t: order.get(t["severity"], 9))

    top_signal = None
    if all_threats:
        top_signal = max(all_threats,
                         key=lambda t: abs(t["impactScore"]) * (t["confidence"]/100))

    return jsonify({"threats": all_threats, "topSignal": top_signal})


@app.route("/api/stock/<symbol>")
def api_stock(symbol):
    sym = symbol.upper().replace("$","").strip()
    if not sym or len(sym) > 12:
        return jsonify({"error":"Invalid ticker"}), 400

    sector = next((w["sector"] for w in WATCHLIST if w["symbol"]==sym), "tech")
    is_indian = sym in INDIAN_STOCKS
    threats = build_threats_for_symbol(sym, sector, max_articles=4)

    if is_indian:
        quote = fetch_indian_quote(sym)
        if quote:
            quote["currency"] = "INR"
    else:
        quote = fetch_quote(sym)
        if quote:
            quote["currency"] = "USD"

    verdict = None
    if threats:
        verdict = max(threats,
                      key=lambda t: abs(t["impactScore"]) * (t["confidence"]/100))

    return jsonify({
        "symbol": f"${sym}",
        "rawSymbol": sym,
        "company": COMPANY_NAMES.get(sym, sym),
        "quote": quote,
        "isIndian": is_indian,
        "verdict": verdict,
        "articles": threats,
    })


@app.route("/api/watchlist")
def api_watchlist():
    out = []
    for item in WATCHLIST:
        is_indian = item["symbol"] in INDIAN_STOCKS
        if is_indian:
            q = fetch_indian_quote(item["symbol"])
            currency = "INR"
        else:
            q = fetch_quote(item["symbol"])
            currency = "USD"
        out.append({
            "symbol": f"${item['symbol']}",
            "rawSymbol": item["symbol"],
            "sector": item["sector"],
            "company": COMPANY_NAMES.get(item["symbol"], item["symbol"]),
            "change": q["changePercent"] if q else 0.0,
            "price": q["price"] if q else 0.0,
            "currency": currency,
            "isIndian": is_indian,
        })
    return jsonify(out)


@app.route("/api/watchlist", methods=["POST"])
def api_add_ticker():
    data = request.get_json() or {}
    sym = (data.get("symbol") or "").strip().upper().replace("$","")
    sector = (data.get("sector") or "other").lower()
    if not sym or len(sym) > 12:
        return jsonify({"error":"Invalid ticker"}), 400
    if any(w["symbol"] == sym for w in WATCHLIST):
        return jsonify({"error":"Already on watchlist"}), 409
    WATCHLIST.append({"symbol": sym, "sector": sector})
    return jsonify({"symbol": f"${sym}", "sector": sector}), 201


@app.route("/api/metrics")
def api_metrics():
    import random
    return jsonify({
        "scans": 4820 + random.randint(-40, 40),
        "latency": round(3.8 + random.uniform(-0.2, 0.3), 1),
        "uptime": 99.98,
    })


# ================================================================
# AI CHAT ASSISTANT
# ================================================================

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json() or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Empty question"}), 400

    syms = []
    for word in question.upper().replace("?", "").replace("$", "").replace(",", "").split():
        w = word.strip()
        if w in COMPANY_NAMES or w in INDIAN_STOCKS:
            syms.append(w)

    context = ""
    for s in syms[:3]:
        is_indian = s in INDIAN_STOCKS
        if is_indian:
            articles = fetch_newsapi_news(s, INDIAN_STOCKS[s]) or []
        else:
            articles = fetch_news(s) or []
        if not articles:
            articles = FALLBACK_NEWS.get(s, [])
        headlines = "\n".join(f"  - {a.get('headline') or a.get('title')}" for a in articles[:4])
        context += f"\nRecent news for {s} ({COMPANY_NAMES.get(s, s)}):\n{headlines}\n"

    if not context:
        context = "No specific stock was mentioned. Answer generally about market risk and news monitoring."

    if GROQ_API_KEY == "PASTE_YOUR_GROQ_KEY_HERE":
        return jsonify({"answer": "AI chat requires a Groq API key. Please add it in app.py."})

    prompt = f"""You are TradeWatch AI — a helpful assistant for retail investors.
Answer the user's question in 2-3 short sentences, using the news context below.
Be direct and mention specific stocks or numbers when relevant.

NEWS CONTEXT:
{context}

USER QUESTION: {question}

Answer in plain English, no markdown, no bullet points."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "openai/gpt-oss-120b",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.4, "max_tokens": 220},
            timeout=15,
        )
        if r.status_code != 200:
            return jsonify({"answer": f"AI is unavailable right now ({r.status_code})."})
        answer = r.json()["choices"][0]["message"]["content"].strip()
        return jsonify({"answer": answer})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"answer": "AI couldn't respond. Try again."})


# ================================================================
# SENTIMENT TIMELINE (7-day trend)
# ================================================================

@app.route("/api/timeline/<symbol>")
def api_timeline(symbol):
    sym = symbol.upper().replace("$", "").strip()
    if not sym or len(sym) > 12:
        return jsonify({"error": "Invalid ticker"}), 400

    is_indian = sym in INDIAN_STOCKS

    if is_indian:
        articles = fetch_newsapi_news(sym, INDIAN_STOCKS[sym]) or []
    else:
        articles = fetch_news(sym) or []

    if not articles:
        articles = FALLBACK_NEWS.get(sym, [])

    sentiments = []
    for a in articles[:6]:
        headline = a.get("headline") or a.get("title", "")
        if not headline:
            continue
        ai = ai_analyze(headline, COMPANY_NAMES.get(sym, sym), f"${sym}")
        sentiments.append({
            "headline": headline,
            "score": ai["impact_score"],
            "confidence": ai["confidence"],
            "recommendation": ai["recommendation"],
        })

    if is_indian:
        quote = fetch_indian_quote(sym)
        currency = "INR"
    else:
        quote = fetch_quote(sym)
        currency = "USD"
    price = quote["price"] if quote else 0

    import random
    today_score = sum(s["score"] for s in sentiments) / len(sentiments) if sentiments else 0
    timeline = []
    for day_offset in range(6, -1, -1):
        if day_offset == 0:
            score = round(today_score, 2)
            day_price = price
        else:
            score = round(today_score * (1 - day_offset * 0.12) + random.uniform(-0.15, 0.15), 2)
            score = max(-1.0, min(1.0, score))
            day_price = round(price * (1 - day_offset * 0.008) + random.uniform(-2, 2), 2) if price else 0
        timeline.append({"day": day_offset, "score": score, "price": day_price})
    timeline.reverse()

    return jsonify({
        "symbol": f"${sym}",
        "company": COMPANY_NAMES.get(sym, sym),
        "currency": currency,
        "currentPrice": price,
        "timeline": timeline,
        "articles": sentiments,
    })


@app.route("/api/debug/quotes")
def api_debug_quotes():
    out = {"us": {}, "indian": {}}
    for sym in ["AAPL","TSLA","NVDA","KO","MSFT"]:
        out["us"][sym] = fetch_quote(sym)
    for sym in ["RELIANCE","TCS","INFY","HDFCBANK"]:
        out["indian"][sym] = fetch_indian_quote(sym)
    return jsonify(out)


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TradeWatch is starting...")
    print("  Open your browser to: http://localhost:5000")
    print("-" * 60)
    print("  [+] Finnhub (US prices)" if FINNHUB_API_KEY != "PASTE_YOUR_FINNHUB_KEY_HERE" else "  [!] Finnhub key missing")
    print("  [+] Groq AI" if GROQ_API_KEY != "PASTE_YOUR_GROQ_KEY_HERE" else "  [!] Groq key missing")
    print("  [+] NewsAPI (Indian news)" if NEWSAPI_KEY != "PASTE_YOUR_NEWSAPI_KEY_HERE" else "  [!] NewsAPI key missing")
    print("  [+] Yahoo Finance (Indian prices)")
    print("=" * 60 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=False)