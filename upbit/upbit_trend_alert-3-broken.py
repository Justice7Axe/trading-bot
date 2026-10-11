import ccxt
import pandas as pd
import requests
import time
from datetime import datetime

# Telegram ?¤ì •
# TELEGRAM_TOKEN = '?¬ê¸°???”ë ˆê·¸ë¨_ë´?? í°_?…ë ¥'
# TELEGRAM_CHAT_ID = '?¬ê¸°??ì±„íŒ…_ID_?…ë ¥'

# def send_telegram_message(message: str):
#     url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
#     data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
#     requests.post(url, data=data)

# ?…ë¹„??API ì´ˆê¸°??upbit = ccxt.upbit()

def get_krw_tickers():
    try:
        print("?“¡ ?…ë¹„??ë§ˆì¼“ ?•ë³´ ë¡œë”© ì¤?..")
        markets = upbit.load_markets()
        
        # ?”ë²„ê¹? ì²˜ìŒ 5ê°??¬ë³¼ ?•ì¸
        all_symbols = list(markets.keys())
        print(f"?” ?„ì²´ ?¬ë³¼ ê°œìˆ˜: {len(all_symbols)}")
        print(f"?” ì²˜ìŒ 5ê°??¬ë³¼: {all_symbols[:5]}")
        
        # KRWë¡??œì‘?˜ëŠ” ?¬ë³¼ ì°¾ê¸° (?¤ì–‘???¨í„´ ?œë„)
        krw_patterns = ['KRW/', 'KRW-', '/KRW']
        krw_tickers = []
        
        for pattern in krw_patterns:
            if pattern == '/KRW':
                found = [symbol for symbol in markets if symbol.endswith(pattern)]
            else:
                found = [symbol for symbol in markets if symbol.startswith(pattern)]
            
            if found:
                print(f"??'{pattern}' ?¨í„´?¼ë¡œ {len(found)}ê°?ë°œê²¬")
                krw_tickers = found
                break
        
        if not krw_tickers:
            print("? ï¸ KRW ë§ˆì¼“??ì°¾ì„ ???†ì–´ BTC ë§ˆì¼“?¼ë¡œ ?ŒìŠ¤??)
            krw_tickers = [symbol for symbol in markets if 'BTC' in symbol][:5]
        
        return krw_tickers
    except Exception as e:
        print(f"??ë§ˆì¼“ ?•ë³´ ë¡œë”© ?¤íŒ¨: {e}")
        return []

def get_ohlcv(symbol, timeframe='4h'):
    try:
        # ?œê°„?€ë³??°ì´??ê°œìˆ˜ ?¤ì •
        if timeframe == '4h':
            limit = 300
        else:  # 1h
            limit = 500
            
        data = upbit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"{symbol} {timeframe} OHLCV ê°€?¸ì˜¤ê¸??¤íŒ¨: {e}")
        return None

def get_current_price(symbol):
    """?„ì¬ ê°€ê²?ì¡°íšŒ"""
    try:
        ticker = upbit.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        print(f"{symbol} ?„ì¬ ê°€ê²?ì¡°íšŒ ?¤íŒ¨: {e}")
        return None

def get_volume_ranking():
    """ê±°ë˜???ìœ„ 20ê°?ì¢…ëª© ì¡°íšŒ"""
    print(f"\n?“Š ê±°ë˜???ìœ„ 20ê°?ì¢…ëª© ë¶„ì„ ?œì‘")
    tickers = get_krw_tickers()
    print(f"?“ˆ ì´?{len(tickers)}ê°?ì½”ì¸ ì¤?ê±°ë˜???ìœ„ 20ê°?? ë³„ ì¤?..")
    
    volume_data = []
    
    for i, symbol in enumerate(tickers):
        try:
            # ?°ì»¤ ?•ë³´ ì¡°íšŒ (?„ì¬ê°€, ê±°ë˜?? ?±ë½ë¥??¬í•¨)
            ticker = upbit.fetch_ticker(symbol)
            
            if ticker:
                # 24?œê°„ ê±°ë˜??(KRW ê¸°ì?)
                volume_krw = ticker.get('quoteVolume', 0)  # KRW ê±°ë˜??                volume_coin = ticker.get('baseVolume', 0)   # ì½”ì¸ ê±°ë˜??                
                # ?„ì¬ê°€
                current_price = ticker.get('last', 0)
                
                # ?„ì¼ ?€ë¹??±ë½ë¥?(%)
                change_percent = ticker.get('percentage', 0)
                
                # ?„ì¼ ì¢…ê?
                previous_close = ticker.get('open', current_price)
                
                volume_data.append({
                    'symbol': symbol,
                    'current_price': current_price,
                    'volume_krw': volume_krw,
                    'volume_coin': volume_coin,
                    'change_percent': change_percent,
                    'previous_close': previous_close
                })
        
        except Exception as e:
            continue
        
        # API ?”ì²­ ?œí•œ ë°©ì?
        time.sleep(0.05)
    
    # ê±°ë˜??KRW) ê¸°ì??¼ë¡œ ?´ë¦¼ì°¨ìˆœ ?•ë ¬
    volume_data.sort(key=lambda x: x['volume_krw'], reverse=True)
    
    # ?ìœ„ 20ê°œë§Œ ? íƒ
    top_20 = volume_data[:20]
    
    # ê²°ê³¼ ì¶œë ¥
    print(f"\n?† ê±°ë˜???ìœ„ 20ê°?ì¢…ëª© (24?œê°„ ê¸°ì?)")
    print("=" * 100)
    print(f"{'?œìœ„':<4} {'ì¢…ëª©':<15} {'?„ì¬ê°€':<15} {'?„ì¼?€ë¹?:<12} {'ê±°ë˜??KRW)':<20}")
    print("-" * 100)
    
    for i, coin in enumerate(top_20):
        rank = i + 1
        symbol = coin['symbol'].replace('KRW/', '').replace('/KRW', '')
        current_price = coin['current_price']
        change_percent = coin['change_percent']
        volume_krw = coin['volume_krw']
        
        # ?±ë½ë¥ ì— ?°ë¥¸ ?´ëª¨ì§€
        if change_percent > 0:
            change_emoji = "?“ˆ"
            change_color = "+"
        elif change_percent < 0:
            change_emoji = "?“‰"
            change_color = ""
        else:
            change_emoji = "?¡ï¸"
            change_color = ""
        
        # ê±°ë˜?‰ì„ ???¨ìœ„ë¡?ë³€??        volume_display = f"{volume_krw/100000000:.1f}?? if volume_krw >= 100000000 else f"{volume_krw/10000:.0f}ë§?
        
        print(f"{rank:<4} {symbol:<15} {current_price:>12,.0f}??{change_emoji} {change_color}{change_percent:>6.2f}% {volume_display:>15}")
    
    print("-" * 100)
    print(f"?“… ì¡°íšŒ ?œê°„: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return top_20

def analyze_xrp_golden_cross():
    """XRP/KRW ì½”ì¸??4?œê°„ ê¸°ì? 50MA?€ 200MA ê³¨ë“ ?¬ë¡œ??ë¶„ì„ (ê°œì„ ??ë²„ì „)"""
    print(f"\n?” XRP/KRW ê³¨ë“ ?¬ë¡œ??ë¶„ì„ ?œì‘")
    
    # XRP ?¬ë³¼ ì°¾ê¸°
    tickers = get_krw_tickers()
    xrp_symbol = None
    
    for ticker in tickers:
        if 'XRP' in ticker.upper():
            xrp_symbol = ticker
            break
    
    if not xrp_symbol:
        print("??XRP/KRW ?¬ë³¼??ì°¾ì„ ???†ìŠµ?ˆë‹¤.")
        return
    
    print(f"?“Š ë¶„ì„ ?€?? {xrp_symbol}")
    
    # 4?œê°„ ?°ì´??ì¡°íšŒ (ìµœë???ë§ì? ?°ì´???•ë³´ - 5000ê°? ??2.5?„ì¹˜)
    try:
        # ?…ë¹„??API ?œí•œ??ê³ ë ¤?˜ì—¬ ?¬ëŸ¬ ë²ˆì— ?˜ëˆ„???°ì´???˜ì§‘
        all_data = []
        limit_per_request = 200  # ??ë²ˆì— ê°€?¸ì˜¬ ?°ì´??ê°œìˆ˜
        total_requests = 10      # ì´??”ì²­ ?Ÿìˆ˜ (200 * 10 = 2000ê°?
        
        print(f"ï¿?{total_requests}ë²ˆì— ?˜ëˆ„???°ì´???˜ì§‘ ì¤?..")
        
        for i in range(total_requests):
            try:
                if i == 0:
                    # ì²?ë²ˆì§¸ ?”ì²­?€ ìµœì‹  ?°ì´?°ë???                    data = upbit.fetch_ohlcv(xrp_symbol, timeframe='4h', limit=limit_per_request)
                else:
                    # ?´í›„ ?”ì²­?€ ?´ì „ ?°ì´?°ì˜ ?œì‘?ë???ê³¼ê±°ë¡?                    since = int(all_data[0][0]) - (limit_per_request * 4 * 60 * 60 * 1000)  # 4?œê°„ * limit_per_requestë§Œí¼ ê³¼ê±°
                    data = upbit.fetch_ohlcv(xrp_symbol, timeframe='4h', limit=limit_per_request, since=since)
                
                if data and len(data) > 0:
                    # ì¤‘ë³µ ?œê±°ë¥??„í•´ ?œì‘ ë¶€ë¶„ì— ì¶”ê?
                    all_data = data + all_data
                    print(f"   ?“Š {i+1}/{total_requests} ?„ë£Œ - ?„ì  ?°ì´?? {len(all_data)}ê°?)
                else:
                    print(f"   ? ï¸ {i+1}/{total_requests} ?°ì´???†ìŒ")
                    break
                
                # API ?”ì²­ ?œí•œ ë°©ì?
                time.sleep(0.1)
                
            except Exception as e:
                print(f"   ??{i+1}/{total_requests} ?”ì²­ ?¤íŒ¨: {e}")
                break
        
        # ì¤‘ë³µ ?œê±° ë°??•ë ¬
        df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        
        print(f"?“ˆ ìµœì¢… ?°ì´??ê¸°ê°„: {df.iloc[0]['timestamp'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['timestamp'].strftime('%Y-%m-%d')}")
        print(f"?“Š ìµœì¢… ?°ì´??ê°œìˆ˜: {len(df)}ê°?)
        
    except Exception as e:
        print(f"??XRP ?°ì´??ì¡°íšŒ ?¤íŒ¨: {e}")
        return
    
    if len(df) < 200:
        print("??ì¶©ë¶„???°ì´?°ê? ?†ìŠµ?ˆë‹¤. (200ê°?ë¯¸ë§Œ)")
        return
    
    # ?°ì´???ˆì§ˆ ?•ì¸
    print(f"\n?” ?°ì´???ˆì§ˆ ?•ì¸:")
    print(f"   ?“Š Close ê°€ê²?ë²”ìœ„: {df['close'].min():.4f} ~ {df['close'].max():.4f} KRW")
    print(f"   ?“Š Close ê°€ê²?NaN ê°œìˆ˜: {df['close'].isna().sum()}ê°?)
    print(f"   ?“Š Close ê°€ê²?0 ê°œìˆ˜: {(df['close'] == 0).sum()}ê°?)
    
    # NaN?´ë‚˜ 0??ê°’ë“¤???œê±°?˜ê±°??ë³´ì •
    df = df.dropna(subset=['close'])  # NaN ?œê±°
    df = df[df['close'] > 0]  # 0??ê°??œê±°
    
    print(f"   ???•ì œ ???°ì´??ê°œìˆ˜: {len(df)}ê°?)
    
    if len(df) < 200:
        print("???•ì œ ??ì¶©ë¶„???°ì´?°ê? ?†ìŠµ?ˆë‹¤. (200ê°?ë¯¸ë§Œ)")
        return
    
    # ?´ë™?‰ê·  ê³„ì‚° (ê°œì„ ??ë°©ë²•)
    print(f"\n?” ?´ë™?‰ê·  ê³„ì‚° ì¤?..")
    
    # ?°ì´?°ê? ì¶©ë¶„?œì? ?•ì¸
    if len(df) < 250:  # MA200 + ?¬ìœ ë¶?50
        print(f"??MA200 ê³„ì‚°???„í•œ ì¶©ë¶„???°ì´?°ê? ?†ìŠµ?ˆë‹¤. (?„ì¬: {len(df)}ê°? ?„ìš”: 250ê°??´ìƒ)")
        return
    
    # ?´ë™?‰ê·  ê³„ì‚° (min_periods ?†ì´ ê³„ì‚°?˜ì—¬ ??ë§ì? ?°ì´???•ë³´)
    df['ma50'] = df['close'].rolling(window=50, center=False).mean()
    df['ma200'] = df['close'].rolling(window=200, center=False).mean()
    
    # MA ê³„ì‚° ê²°ê³¼ ?•ì¸
    ma50_valid = df['ma50'].notna().sum()
    ma200_valid = df['ma200'].notna().sum()
    ma50_first_valid = df['ma50'].first_valid_index()
    ma200_first_valid = df['ma200'].first_valid_index()
    
    print(f"   ?“ˆ MA50 ? íš¨ ?°ì´?? {ma50_valid}ê°?(?œì‘ ?¸ë±?? {ma50_first_valid})")
    print(f"   ?“Š MA200 ? íš¨ ?°ì´?? {ma200_valid}ê°?(?œì‘ ?¸ë±?? {ma200_first_valid})")
    
    # MA200??? íš¨???°ì´?°ë??°ë§Œ ?¬ìš©
    if ma200_first_valid is not None:
        df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
        print(f"   ??MA200 ? íš¨ êµ¬ê°„ ?°ì´?? {len(df_valid)}ê°?)
        
        # ? íš¨ êµ¬ê°„??ìµœê·¼ ?°ì´??MA ê°??•ì¸
        if len(df_valid) > 0:
            latest_valid = df_valid.iloc[-1]
            print(f"   ?’° ìµœê·¼ ì¢…ê?: {latest_valid['close']:.4f} KRW")
            print(f"   ?“ˆ ìµœê·¼ MA50: {latest_valid['ma50']:.4f} KRW")
            print(f"   ?“Š ìµœê·¼ MA200: {latest_valid['ma200']:.4f} KRW")
            
            # ? íš¨???°ì´?°ë¡œ êµì²´
            df = df_valid
    else:
        print(f"   ??MA200 ê³„ì‚° ê°€?¥í•œ ?°ì´?°ê? ?†ìŠµ?ˆë‹¤.")
        return
    
    # ìµœê·¼ ?°ì´???˜í”Œ ?•ì¸ (MA ê³„ì‚°???œë?ë¡??˜ëŠ”ì§€ ?•ì¸)
    print(f"\n?” ìµœê·¼ ?°ì´???˜í”Œ ?•ì¸ (MA ê³„ì‚° ê²€ì¦?:")
    recent_sample = df.tail(10)  # ìµœê·¼ 10ê°??°ì´??    for _, row in recent_sample.iterrows():
        ma_diff = row['ma50'] - row['ma200'] if not (pd.isna(row['ma50']) or pd.isna(row['ma200'])) else 0
        status = "?ŒŸ" if row['ma50'] > row['ma200'] else "??" if not (pd.isna(row['ma50']) or pd.isna(row['ma200'])) else "??
        print(f"   {status} {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | ì°¨ì´: {ma_diff:+.4f}")
    
    # 2025??7??6-7??ì£¼ë? ?°ì´???”ë²„ê¹?    print(f"\n?” 2025??7??6-7??ì£¼ë? ?°ì´???•ì¸:")
    july_2025_data = df[(df['timestamp'] >= '2025-07-01') & (df['timestamp'] <= '2025-07-15')]
    if len(july_2025_data) > 0:
        print(f"?“… 2025??7??1??15???°ì´?? {len(july_2025_data)}ê°?)
        for _, row in july_2025_data.iterrows():
            if pd.isna(row['ma50']) or pd.isna(row['ma200']):
                print(f"   ? ï¸ {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | MA50: NaN | MA200: NaN | ì¢…ê?: {row['close']:.4f}")
            else:
                ma_diff = row['ma50'] - row['ma200']
                status = "?ŒŸ" if row['ma50'] > row['ma200'] else "??"
                print(f"   {status} {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | ì°¨ì´: {ma_diff:+.4f}")
    else:
        print("??2025??7???°ì´?°ë? ì°¾ì„ ???†ìŠµ?ˆë‹¤. (ë¯¸ë˜ ?°ì´??")
        
        # ?„ì¬ ?°ì´?°ì˜ ìµœì‹  ? ì§œ ?•ì¸
        if len(df) > 0:
            latest_date = df.iloc[-1]['timestamp']
            print(f"   ?“… ?„ì¬ ?°ì´?°ì˜ ìµœì‹  ? ì§œ: {latest_date.strftime('%Y-%m-%d %H:%M')}")
            print(f"   ?“Š 2025??7?”ê¹Œì§€ ?¨ì? ê¸°ê°„: ë¯¸ë˜ ?°ì´?°ì´ë¯€ë¡?ì¡´ì¬?˜ì? ?ŠìŒ")
    
    # ê³¨ë“ ?¬ë¡œ??ì°¾ê¸° (ê°œì„ ??ë¡œì§)
    golden_crosses = []
    death_crosses = []
    
    print(f"\n?” ê³¨ë“ ?¬ë¡œ???ì? ì¤?..")
    
    # 200ë²ˆì§¸ ?¸ë±?¤ë????œì‘ (MA200??? íš¨??ê°’ì„ ê°€ì§€???œì ë¶€??
    for i in range(200, len(df)):
        prev_row = df.iloc[i-1]
        curr_row = df.iloc[i]
        
        # NaN ê°?ì²´í¬
        if (pd.isna(prev_row['ma50']) or pd.isna(prev_row['ma200']) or
            pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200'])):
            continue
        
        # ê³¨ë“ ?¬ë¡œ??ì¡°ê±´ ê°œì„ : ???•í™•???¬ë¡œ???ì?
        prev_ma_diff = prev_row['ma50'] - prev_row['ma200']
        curr_ma_diff = curr_row['ma50'] - curr_row['ma200']
        
        # ê³¨ë“ ?¬ë¡œ?? ?´ì „?ëŠ” MA50 < MA200, ?„ì¬??MA50 > MA200 (?±í˜¸ ?œê±°)
        if prev_ma_diff < 0 and curr_ma_diff > 0:
            golden_crosses.append({
                'date': curr_row['timestamp'],
                'price': curr_row['close'],
                'ma50': curr_row['ma50'],
                'ma200': curr_row['ma200'],
                'prev_diff': prev_ma_diff,
                'curr_diff': curr_ma_diff
            })
            
            # 2024?„ê³¼ 2025??7??6-7??ê·¼ì²˜ ê³¨ë“ ?¬ë¡œ???”ë²„ê¹?            if curr_row['timestamp'].month == 7 and curr_row['timestamp'].day in [5, 6, 7] and curr_row['timestamp'].year == 2025:
                print(f"?¯ 2025??7??{curr_row['timestamp'].day}??ê³¨ë“ ?¬ë¡œ??ë°œê²¬!")
                print(f"   ï¿??œê°„: {curr_row['timestamp'].strftime('%Y-%m-%d %H:%M')}")
                print(f"   ï¿? ê°€ê²? {curr_row['close']:.4f} KRW")
                print(f"   ?“ˆ ?´ì „ ì°¨ì´: {prev_ma_diff:+.6f} ???„ì¬ ì°¨ì´: {curr_ma_diff:+.6f}")
        
        # ?°ë“œ?¬ë¡œ?? ?´ì „?ëŠ” MA50 > MA200, ?„ì¬??MA50 < MA200
        elif prev_ma_diff > 0 and curr_ma_diff < 0:
            death_crosses.append({
                'date': curr_row['timestamp'],
                'price': curr_row['close'],
                'ma50': curr_row['ma50'],
                'ma200': curr_row['ma200'],
                'prev_diff': prev_ma_diff,
                'curr_diff': curr_ma_diff
            })
    
    # ?„ì¬ ?íƒœ ?•ì¸
    latest = df.iloc[-1]
    current_price = get_current_price(xrp_symbol)
    
    # MA ê°’ì´ ? íš¨?œì? ?•ì¸
    ma50_valid = not pd.isna(latest['ma50'])
    ma200_valid = not pd.isna(latest['ma200'])
    
    if ma50_valid and ma200_valid:
        is_golden_cross = latest['ma50'] > latest['ma200']
        ma_diff = latest['ma50'] - latest['ma200']
    else:
        is_golden_cross = False
        ma_diff = 0
    
    # ê²°ê³¼ ì¶œë ¥
    print(f"\n?“Š XRP/KRW ê³¨ë“ ?¬ë¡œ??ë¶„ì„ ê²°ê³¼")
    print("=" * 80)
    print(f"?’° ?„ì¬ê°€: {current_price:,.4f} KRW" if current_price else f"?’° ?„ì¬ê°€: {latest['close']:,.4f} KRW")
    
    if ma50_valid:
        print(f"?“ˆ MA50: {latest['ma50']:,.4f} KRW")
    else:
        print(f"?“ˆ MA50: NaN (?°ì´??ë¶€ì¡?- ìµœì†Œ 50ê°??„ìš”)")
        
    if ma200_valid:
        print(f"?“Š MA200: {latest['ma200']:,.4f} KRW")
    else:
        print(f"?“Š MA200: NaN (?°ì´??ë¶€ì¡?- ìµœì†Œ 200ê°??„ìš”)")
    
    if ma50_valid and ma200_valid:
        print(f"?“ MA ì°¨ì´: {ma_diff:+.4f} KRW")
        print(f"?”„ ?„ì¬ ?íƒœ: {'?ŒŸ ê³¨ë“ ?¬ë¡œ???íƒœ' if is_golden_cross else '?? ?°ë“œ?¬ë¡œ???íƒœ'}")
    else:
        print(f"?“ MA ì°¨ì´: ê³„ì‚° ë¶ˆê? (MA ê°?ë¶€ì¡?")
        print(f"?”„ ?„ì¬ ?íƒœ: ???ë‹¨ ë¶ˆê? (MA ?°ì´??ë¶€ì¡?")
    
    if golden_crosses:
        print(f"\n?ŒŸ ê³¨ë“ ?¬ë¡œ??ë°œìƒ ?´ë ¥ ({len(golden_crosses)}??")
        print("-" * 80)
        
        for i, cross in enumerate(golden_crosses):
            days_ago = (datetime.now() - cross['date'].to_pydatetime()).days
            print(f"{i+1:2d}. ?“… {cross['date'].strftime('%Y-%m-%d %H:%M')} ({days_ago}????")
            print(f"     ?’° ê°€ê²? {cross['price']:,.4f} KRW")
            print(f"     ?“ˆ MA50: {cross['ma50']:,.4f} KRW | MA200: {cross['ma200']:,.4f} KRW")
            print(f"     ?“ ?¬ë¡œ??ì°¨ì´: {cross['prev_diff']:+.6f} ??{cross['curr_diff']:+.6f}")
            
            # ?„ì¬ ê°€ê²©ê³¼ ë¹„êµ?˜ì—¬ ?˜ìµë¥?ê³„ì‚°
            if current_price:
                profit_rate = ((current_price - cross['price']) / cross['price']) * 100
                profit_emoji = "?“ˆ" if profit_rate > 0 else "?“‰"
                print(f"     {profit_emoji} ?„ì¬ ?€ë¹??˜ìµë¥? {profit_rate:+.2f}%")
            print()
    else:
        print("\n??ë¶„ì„ ê¸°ê°„ ??ê³¨ë“ ?¬ë¡œ??ë°œìƒ ?´ë ¥???†ìŠµ?ˆë‹¤.")
        print("?” ?”ë²„ê¹? 7??6??ì£¼ë? MA ì°¨ì´ê°’ì„ ?•ì¸?´ë³´?¸ìš”.")
    
    if death_crosses:
        print(f"\n?? ?°ë“œ?¬ë¡œ??ë°œìƒ ?´ë ¥ ({len(death_crosses)}??")
        print("-" * 80)
        
        for i, cross in enumerate(death_crosses):
            days_ago = (datetime.now() - cross['date'].to_pydatetime()).days
            print(f"{i+1:2d}. ?“… {cross['date'].strftime('%Y-%m-%d %H:%M')} ({days_ago}????")
            print(f"     ?’° ê°€ê²? {cross['price']:,.4f} KRW")
            print(f"     ?“ˆ MA50: {cross['ma50']:,.4f} KRW | MA200: {cross['ma200']:,.4f} KRW")
            print(f"     ?“ ?¬ë¡œ??ì°¨ì´: {cross['prev_diff']:+.6f} ??{cross['curr_diff']:+.6f}")
            print()
    
    # ìµœê·¼ ê³¨ë“ ?¬ë¡œ???°ë“œ?¬ë¡œ???•ë³´
    if golden_crosses:
        latest_golden = golden_crosses[-1]
        days_since_golden = (datetime.now() - latest_golden['date'].to_pydatetime()).days
        print(f"?ŒŸ ìµœê·¼ ê³¨ë“ ?¬ë¡œ?? {latest_golden['date'].strftime('%Y-%m-%d %H:%M')} ({days_since_golden}????")
    
    if death_crosses:
        latest_death = death_crosses[-1]
        days_since_death = (datetime.now() - latest_death['date'].to_pydatetime()).days
        print(f"?? ìµœê·¼ ?°ë“œ?¬ë¡œ?? {latest_death['date'].strftime('%Y-%m-%d %H:%M')} ({days_since_death}????")
    
    # 2025??7??6-7???¹ë³„ ?•ì¸
    print(f"\n?¯ 2025??7??6???¹ë³„ ë¶„ì„:")
    july_6_2025_data = df[df['timestamp'].dt.date == pd.to_datetime('2025-07-06').date()]
    if len(july_6_2025_data) > 0:
        for _, row in july_6_2025_data.iterrows():
            ma_diff = row['ma50'] - row['ma200']
            status = "?ŒŸ ê³¨ë“ ?¬ë¡œ?? if row['ma50'] > row['ma200'] else "?? ?°ë“œ?¬ë¡œ??
            print(f"   ?“… {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | {status}")
            print(f"   ?“ˆ MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | ì°¨ì´: {ma_diff:+.6f}")
    else:
        print(f"   ??2025??7??6???°ì´?°ë? ì°¾ì„ ???†ìŠµ?ˆë‹¤. (ë¯¸ë˜ ?°ì´??")
    
    print(f"\n?¯ 2025??7??7???¹ë³„ ë¶„ì„:")
    july_7_2025_data = df[df['timestamp'].dt.date == pd.to_datetime('2025-07-07').date()]
    if len(july_7_2025_data) > 0:
        for _, row in july_7_2025_data.iterrows():
            ma_diff = row['ma50'] - row['ma200']
            status = "?ŒŸ ê³¨ë“ ?¬ë¡œ?? if row['ma50'] > row['ma200'] else "?? ?°ë“œ?¬ë¡œ??
            print(f"   ?“… {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | {status}")
            print(f"   ?“ˆ MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | ì°¨ì´: {ma_diff:+.6f}")
    else:
        print(f"   ??2025??7??7???°ì´?°ë? ì°¾ì„ ???†ìŠµ?ˆë‹¤. (ë¯¸ë˜ ?°ì´??")
    
    # 2025??7??6-7??ê³¨ë“ ?¬ë¡œ??ë¹„êµ ë¶„ì„
    all_target_dates = [
        ('2025-07-06', july_6_2025_data),
        ('2025-07-07', july_7_2025_data)
    ]
    
    golden_cross_dates = []
    for date_str, data in all_target_dates:
        if len(data) > 0:
            for _, row in data.iterrows():
                if row['ma50'] > row['ma200']:
                    golden_cross_dates.append({
                        'date': date_str,
                        'timestamp': row['timestamp'],
                        'price': row['close'],
                        'ma_diff': row['ma50'] - row['ma200']
                    })
    
    if golden_cross_dates:
        print(f"\n?ŒŸ ëª©í‘œ ? ì§œ?¤ì˜ ê³¨ë“ ?¬ë¡œ???íƒœ ?”ì•½:")
        print("-" * 60)
        for cross in golden_cross_dates:
            print(f"??{cross['date']} | ê°€ê²? {cross['price']:.4f} KRW | MAì°¨ì´: {cross['ma_diff']:+.6f}")
    else:
        print(f"\n??ëª©í‘œ ? ì§œ??2025??7??6-7?? ì¤?ê³¨ë“ ?¬ë¡œ???íƒœ??? ì§œê°€ ?†ìŠµ?ˆë‹¤.")

def analyze_golden_cross_reliability(df, cross_index, cross_row):
    """ê³¨ë“ ?¬ë¡œ??? í˜¸??? ë¢°??ë¶„ì„"""
    
    # ê³¨ë“ ?¬ë¡œ???´í›„ 3-4ê°?ìº”ë“¤ ë¶„ì„ (ìµœë? 4ê°œê¹Œì§€)
    after_candles = []
    for i in range(1, min(5, len(df) - cross_index)):
        if cross_index + i < len(df):
            after_candles.append(df.iloc[cross_index + i])
    
    # 1. ?‘ë´‰ ìº”ë“¤ ê°•ë„ ë¶„ì„
    bullish_candles = 0
    strong_bullish = 0
    
    for candle in after_candles:
        if candle['close'] > candle['open']:  # ?‘ë´‰
            bullish_candles += 1
            body_size = (candle['close'] - candle['open']) / candle['open'] * 100
            if body_size > 3:  # 3% ?´ìƒ ?ìŠ¹ ??ê°•í•œ ?‘ë´‰
                strong_bullish += 1
    
    # 2. ê±°ë˜??ì¦ê? ë¶„ì„
    volume_surge = False
    if cross_index >= 10:  # ì¶©ë¶„??ê³¼ê±° ?°ì´?°ê? ?ˆì„ ??        # ê³¨ë“ ?¬ë¡œ???´ì „ 10ê°?ìº”ë“¤???‰ê·  ê±°ë˜??        prev_volumes = [df.iloc[cross_index - i]['volume'] for i in range(1, 11)]
        avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
        
        # ê³¨ë“ ?¬ë¡œ???œì ê³??´í›„ ìº”ë“¤?¤ì˜ ê±°ë˜??        cross_volume = cross_row['volume']
        after_volumes = [candle['volume'] for candle in after_candles]
        
        # ê±°ë˜?‰ì´ ?‰ê· ??1.5ë°??´ìƒ?´ë©´ ê±°ë˜??ê¸‰ì¦?¼ë¡œ ?ë‹¨
        if cross_volume > avg_prev_volume * 1.5:
            volume_surge = True
        elif after_volumes and max(after_volumes) > avg_prev_volume * 1.5:
            volume_surge = True
    
    # 3. ?€??„  ?ŒíŒŒ ë¶„ì„
    resistance_break = False
    if cross_index >= 20:  # ì¶©ë¶„??ê³¼ê±° ?°ì´?°ê? ?ˆì„ ??        # ê³¨ë“ ?¬ë¡œ???´ì „ 20ê°?ìº”ë“¤??ìµœê³ ê°€??ì¤??ìœ„ ?€??„  ì°¾ê¸°
        prev_highs = [df.iloc[cross_index - i]['high'] for i in range(1, 21)]
        resistance_level = sorted(prev_highs, reverse=True)[2]  # ?ìœ„ 3ë²ˆì§¸ ê³ ì ???€??„ ?¼ë¡œ ?¤ì •
        
        # ê³¨ë“ ?¬ë¡œ???´í›„ ?€??„  ?ŒíŒŒ ?¬ë?
        cross_high = cross_row['high']
        after_highs = [candle['high'] for candle in after_candles]
        
        if cross_high > resistance_level or (after_highs and max(after_highs) > resistance_level):
            resistance_break = True
    
    # 4. ì¢…í•© ? í˜¸ ê°•ë„ ê³„ì‚°
    strength_score = 0
    
    # ?‘ë´‰ ìº”ë“¤ ?ìˆ˜ (ìµœë? 40??
    if bullish_candles >= 3:
        strength_score += 20
    elif bullish_candles >= 2:
        strength_score += 10
    
    if strong_bullish >= 2:
        strength_score += 20
    elif strong_bullish >= 1:
        strength_score += 10
    
    # ê±°ë˜???ìˆ˜ (ìµœë? 30??
    if volume_surge:
        strength_score += 30
    
    # ?€??„  ?ŒíŒŒ ?ìˆ˜ (ìµœë? 30??
    if resistance_break:
        strength_score += 30
    
    # ?¯ ì§„ì… ? í˜¸ ?ë‹¨ ë¡œì§ (?µì‹¬ ?¬ì ê°€?´ë“œ)
    entry_signal = False
    entry_reason = ""
    entry_confidence = 0
    
    # ?“ˆ ì§„ì… ê³ ë ¤ ì¡°ê±´ 1: ê³¨ë“ ?¬ë¡œ??+ ê±°ë˜??+ 3-4ê°??‘ë´‰ + ?€??Œ??(ìµœê°• ? í˜¸)
    if volume_surge and bullish_candles >= 3 and resistance_break:
        entry_signal = True
        entry_reason = "?? ê°•ë ¥??ì§„ì… ? í˜¸"
        entry_confidence = 95
    
    # ?“ˆ ì§„ì… ê³ ë ¤ ì¡°ê±´ 2: ê³¨ë“ ?¬ë¡œ??+ ê±°ë˜??+ 3-4ê°??‘ë´‰ (ê°•í•œ ? í˜¸)
    elif volume_surge and bullish_candles >= 3:
        entry_signal = True
        entry_reason = "?“ˆ ì§„ì… ê³ ë ¤"
        entry_confidence = 80
    
    # ??ì§„ì… ê³ ë ¤ ì¡°ê±´ 3: ê³¨ë“ ?¬ë¡œ??+ ê±°ë˜??+ ?€??Œ??(?ŒíŒŒ ì§„ì…)
    elif volume_surge and resistance_break:
        entry_signal = True
        entry_reason = "???ŒíŒŒ ì§„ì…"
        entry_confidence = 75
    
    # ?” ê´€ì°?ì¡°ê±´: ê³¨ë“ ?¬ë¡œ??+ ê±°ë˜?‰ë§Œ ?ˆëŠ” ê²½ìš°
    elif volume_surge and bullish_candles >= 2:
        entry_signal = False
        entry_reason = "?” ê´€ì°??„ìš”"
        entry_confidence = 60
    
    # ? ï¸ ?˜ì´??ê°€?¥ì„± ?’ìŒ: ê±°ë˜???†ëŠ” ê³¨ë“ ?¬ë¡œ??    elif not volume_surge:
        entry_signal = False
        entry_reason = "? ï¸ ?˜ì´??ê°€?¥ì„± ?’ìŒ"
        entry_confidence = 20
    
    # ?¤” ? ë§¤???í™©
    else:
        entry_signal = False
        entry_reason = "?¤” ? í˜¸ ?½í•¨"
        entry_confidence = 40
    
    # ? ë¢°???ë‹¨
    is_reliable = strength_score >= 60  # 60???´ìƒ?´ë©´ ? ë¢°??ë§Œí•œ ? í˜¸
    
    if strength_score >= 80:
        strength = "ë§¤ìš° ê°•í•¨"
    elif strength_score >= 60:
        strength = "ê°•í•¨"
    elif strength_score >= 40:
        strength = "ë³´í†µ"
    else:
        strength = "?½í•¨"
    
    return {
        'strength': strength,
        'strength_score': strength_score,
        'volume_surge': volume_surge,
        'bullish_candles': bullish_candles,
        'strong_bullish': strong_bullish,
        'resistance_break': resistance_break,
        'is_reliable': is_reliable,
        'entry_signal': entry_signal,
        'entry_reason': entry_reason,
        'entry_confidence': entry_confidence
    }

def analyze_all_coins_golden_cross():
    """?…ë¹„????ì¢…ëª©??2???´ë‚´ ê³¨ë“ ?¬ë¡œ??ë¶„ì„ (? í˜¸ ? ë¢°???¬í•¨)"""
    print(f"\n?” ?…ë¹„????ì¢…ëª© ê³¨ë“ ?¬ë¡œ??ë¶„ì„ ?œì‘ (? í˜¸ ? ë¢°??ë¶„ì„ ?¬í•¨)")
    
    # ëª¨ë“  KRW ì¢…ëª© ê°€?¸ì˜¤ê¸?    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("???…ë¹„??ì¢…ëª©??ê°€?¸ì˜¬ ???†ìŠµ?ˆë‹¤.")
        return
    
    print(f"\n?“Š ì´?{len(all_tickers)}ê°?ì¢…ëª©??2???´ë‚´ ê³¨ë“ ?¬ë¡œ??ë¶„ì„ ì¤?..")
    
    # 2????? ì§œ ê³„ì‚°
    two_months_ago = datetime.now() - pd.Timedelta(days=60)
    print(f"?“… ë¶„ì„ ê¸°ê°„: {two_months_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    golden_cross_results = []
    
    for i, symbol in enumerate(all_tickers):
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"?” ë¶„ì„ ì¤?.. ({i+1}/{len(all_tickers)}) {coin_name}")
        
        try:
            # 4?œê°„ ?°ì´??ì¡°íšŒ (XRP ë¶„ì„ê³??™ì¼??ë°©ì‹?¼ë¡œ ì¶©ë¶„???°ì´???•ë³´)
            all_data = []
            limit_per_request = 200
            total_requests = 5  # 1000ê°??°ì´??(??6ê°œì›”ì¹?
            
            for j in range(total_requests):
                try:
                    if j == 0:
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request)
                    else:
                        since = int(all_data[0][0]) - (limit_per_request * 4 * 60 * 60 * 1000)
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request, since=since)
                    
                    if data and len(data) > 0:
                        all_data = data + all_data
                    else:
                        break
                    
                    time.sleep(0.05)  # ì§§ì? ?œë ˆ??                    
                except Exception as e:
                    break
            
            if not all_data:
                print(f"   ??{coin_name}: ?°ì´??ì¡°íšŒ ?¤íŒ¨")
                continue
            
            # ?°ì´?°í”„?ˆì„ ?ì„± ë°??•ì œ
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 250:
                print(f"   ? ï¸ {coin_name}: ?˜ì§‘???°ì´??ë¶€ì¡?({len(df)}ê°?")
                continue
            
            # ?°ì´???•ì œ
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 250:
                print(f"   ? ï¸ {coin_name}: ?•ì œ ???°ì´??ë¶€ì¡?)
                continue
            
            # ?´ë™?‰ê·  ê³„ì‚°
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200??? íš¨???°ì´?°ë??°ë§Œ ?¬ìš©
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ? ï¸ {coin_name}: MA200 ê³„ì‚° ë¶ˆê?")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 2???´ë‚´ ?°ì´?°ë§Œ ?„í„°ë§?            recent_df = df_valid[df_valid['timestamp'] >= two_months_ago].copy()
            
            if len(recent_df) < 10:
                print(f"   ? ï¸ {coin_name}: 2???´ë‚´ ?°ì´??ë¶€ì¡?)
                continue
            
            # ê³¨ë“ ?¬ë¡œ???ì?
            golden_crosses = []
            
            for j in range(1, len(recent_df)):
                prev_row = recent_df.iloc[j-1]
                curr_row = recent_df.iloc[j]
                
                # NaN ê°?ì²´í¬
                if (pd.isna(prev_row['ma50']) or pd.isna(prev_row['ma200']) or
                    pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200'])):
                    continue
                
                # ê³¨ë“ ?¬ë¡œ??ì¡°ê±´
                prev_ma_diff = prev_row['ma50'] - prev_row['ma200']
                curr_ma_diff = curr_row['ma50'] - curr_row['ma200']
                
                if prev_ma_diff < 0 and curr_ma_diff > 0:
                    days_ago = (datetime.now() - curr_row['timestamp'].to_pydatetime()).days
                    
                    # ?„ì¬ê°€ ì¡°íšŒ
                    current_price = get_current_price(symbol)
                    if current_price is None:
                        current_price = df_valid.iloc[-1]['close']  # ìµœì‹  ì¢…ê? ?¬ìš©
                    
                    # ê³¨ë“ ?¬ë¡œ??? í˜¸ ? ë¢°??ë¶„ì„
                    signal_analysis = analyze_golden_cross_reliability(recent_df, j, curr_row)
                    
                    golden_crosses.append({
                        'symbol': symbol,
                        'coin_name': coin_name,
                        'date': curr_row['timestamp'],
                        'days_ago': days_ago,
                        'price': curr_row['close'],
                        'ma50': curr_row['ma50'],
                        'ma200': curr_row['ma200'],
                        'current_price': current_price,
                        'signal_strength': signal_analysis['strength'],
                        'volume_surge': signal_analysis['volume_surge'],
                        'bullish_candles': signal_analysis['bullish_candles'],
                        'resistance_break': signal_analysis['resistance_break'],
                        'is_reliable': signal_analysis['is_reliable'],
                        'entry_signal': signal_analysis['entry_signal'],
                        'entry_reason': signal_analysis['entry_reason'],
                        'entry_confidence': signal_analysis['entry_confidence']
                    })
            
            if golden_crosses:
                # ê°€??ìµœê·¼ ê³¨ë“ ?¬ë¡œ?¤ë§Œ ?€??                latest_golden_cross = golden_crosses[-1]
                golden_cross_results.append(latest_golden_cross)
                print(f"   ??{coin_name}: {latest_golden_cross['days_ago']}????ê³¨ë“ ?¬ë¡œ??)
            else:
                print(f"   ??{coin_name}: 2???´ë‚´ ê³¨ë“ ?¬ë¡œ???†ìŒ")
        
        except Exception as e:
            print(f"   ??{coin_name}: ë¶„ì„ ?¤íŒ¨ - {e}")
            continue
        
        # API ?”ì²­ ?œí•œ ë°©ì?
        time.sleep(0.1)
    
    # ê²°ê³¼ ì¶œë ¥
    if golden_cross_results:
        # ì§„ì… ? í˜¸ë³„ë¡œ ë¶„ë¥˜
        entry_signals = [r for r in golden_cross_results if r.get('entry_signal', False)]
        reliable_signals = [r for r in golden_cross_results if r.get('is_reliable', False)]
        fake_signals = [r for r in golden_cross_results if not r.get('volume_surge', True)]
        
        print(f"\n?¯ 2???´ë‚´ ê³¨ë“ ?¬ë¡œ??ë°œìƒ ì¢…ëª©: {len(golden_cross_results)}ê°?)
        print(f"?? ì§„ì… ê³ ë ¤ ? í˜¸: {len(entry_signals)}ê°?)
        print(f"?ŒŸ ? ë¢°??ë§Œí•œ ? í˜¸: {len(reliable_signals)}ê°?)
        print(f"? ï¸ ?˜ì´??ê°€?¥ì„± ?’ì? ? í˜¸: {len(fake_signals)}ê°?)
        print("=" * 140)
        
        # ì§„ì… ? í˜¸ ?°ì„ ?¼ë¡œ ?•ë ¬ (ì§„ì… ? í˜¸ ??? ë¢°????ìµœê·¼ ??
        golden_cross_results.sort(key=lambda x: (
            -int(x.get('entry_signal', False)),  # ì§„ì… ? í˜¸ ?°ì„ 
            -x.get('entry_confidence', 0),       # ? ë¢°???’ì? ??            x['days_ago']                        # ìµœê·¼ ??        ))
        
        print(f"{'?œìœ„':<4} {'ì¢…ëª©':<8} {'? ì§œ':<12} {'?¼ìˆ˜':<6} {'ê°€ê²?:<10} {'?„ì¬ê°€':<10} {'?˜ìµë¥?:<8} {'ì§„ì…? í˜¸':<20} {'? ë¢°??:<6} {'ê±°ë˜??:<6} {'?‘ë´‰':<4} {'?ŒíŒŒ':<4}")
        print("-" * 140)
        
        for i, result in enumerate(golden_cross_results):
            rank = i + 1
            coin_name = result['coin_name']
            cross_date = result['date'].strftime('%m-%d')
            days_ago = f"{result['days_ago']}??
            cross_price = f"{result['price']:,.0f}??
            current_price = f"{result['current_price']:,.0f}??
            
            # ?˜ìµë¥?ê³„ì‚°
            profit_rate = ((result['current_price'] - result['price']) / result['price']) * 100
            profit_display = f"{profit_rate:+.1f}%"
            profit_emoji = "?“ˆ" if profit_rate > 0 else "?“‰"
            
            # ì§„ì… ? í˜¸ ?•ë³´
            entry_reason = result.get('entry_reason', '?¤” ? í˜¸ ?½í•¨')
            entry_confidence = result.get('entry_confidence', 0)
            confidence_display = f"{entry_confidence}%" if entry_confidence > 0 else "-"
            
            # ì¡°ê±´ë³??´ëª¨ì§€
            volume_emoji = "?“Š" if result.get('volume_surge', False) else "?“‰"
            bullish_count = result.get('bullish_candles', 0)
            resistance_emoji = "??" if result.get('resistance_break', False) else "?”’"
            
            # ì§„ì… ? í˜¸ê°€ ?ˆëŠ” ì¢…ëª©?€ ê°•ì¡° ?œì‹œ
            prefix = "?¯" if result.get('entry_signal', False) else "  "
            
            print(f"{prefix}{rank:<3} {coin_name:<8} {cross_date:<12} {days_ago:<6} {cross_price:<10} {current_price:<10} {profit_emoji}{profit_display:<7} {entry_reason:<20} {confidence_display:<6} {volume_emoji:<6} {bullish_count}ê°?'':<4} {resistance_emoji:<4}")
        
        print("-" * 140)
        
        # ?“ˆ ì§„ì… ê³ ë ¤ ì¢…ëª© ë³„ë„ ?”ì•½
        if entry_signals:
            print(f"\n?¯ ì§„ì… ê³ ë ¤ ì¢…ëª© ?”ì•½ ({len(entry_signals)}ê°?")
            print("=" * 120)
            print(f"{'ì¢…ëª©':<8} {'ì§„ì…? í˜¸':<20} {'ê³¨ë“ ?¬ë¡œ??ë°œìƒ?œì ':<20} {'? ë¢°??:<8} {'?˜ìµë¥?:<10} {'?„ì¬ê°€':<12}")
            print("-" * 120)
            for signal in entry_signals:
                profit_rate = ((signal['current_price'] - signal['price']) / signal['price']) * 100
                profit_emoji = "?“ˆ" if profit_rate > 0 else "?“‰"
                cross_datetime = signal['date'].strftime('%Y-%m-%d %H:%M')
                current_price_display = f"{signal['current_price']:,.0f}??
                print(f"?? {signal['coin_name']:<6} {signal.get('entry_reason', ''):<20} {cross_datetime:<20} {signal.get('entry_confidence', 0)}%{'':<6} {profit_emoji}{profit_rate:+.1f}%{'':<6} {current_price_display:<12}")
            print("-" * 120)
        
        # ?? ê°•ë ¥??ì§„ì… ? í˜¸ë§?ë³„ë„ ?œì‹œ
        strong_signals = [r for r in entry_signals if r.get('entry_reason') == '?? ê°•ë ¥??ì§„ì… ? í˜¸']
        if strong_signals:
            print(f"\n?”¥ ê°•ë ¥??ì§„ì… ? í˜¸ ì¢…ëª© ({len(strong_signals)}ê°? - ìµœìš°???¬ì ê²€???€??)
            print("=" * 130)
            print(f"{'ì¢…ëª©':<8} {'ê³¨ë“ ?¬ë¡œ??ë°œìƒ?œì ':<20} {'ë°œìƒê°€ê²?:<12} {'?„ì¬ê°€':<12} {'?˜ìµë¥?:<10} {'ê±°ë˜??:<6} {'?‘ë´‰':<6} {'?€??Œ??:<8}")
            print("-" * 130)
            
            # ?˜ìµë¥??œìœ¼ë¡??•ë ¬
            strong_signals.sort(key=lambda x: ((x['current_price'] - x['price']) / x['price']) * 100, reverse=True)
            
            for signal in strong_signals:
                profit_rate = ((signal['current_price'] - signal['price']) / signal['price']) * 100
                profit_emoji = "?“ˆ" if profit_rate > 0 else "?“‰"
                cross_datetime = signal['date'].strftime('%Y-%m-%d %H:%M')
                cross_price = f"{signal['price']:,.0f}??
                current_price_display = f"{signal['current_price']:,.0f}??
                volume_emoji = "?“Š" if signal.get('volume_surge', False) else "?“‰"
                bullish_count = signal.get('bullish_candles', 0)
                resistance_emoji = "??" if signal.get('resistance_break', False) else "?”’"
                
                print(f"?”¥ {signal['coin_name']:<6} {cross_datetime:<20} {cross_price:<12} {current_price_display:<12} {profit_emoji}{profit_rate:+.1f}%{'':<6} {volume_emoji:<6} {bullish_count}ê°?'':<4} {resistance_emoji:<8}")
            
            print("-" * 130)
            
            # ê°•ë ¥??ì§„ì… ? í˜¸ ?µê³„
            strong_profitable = sum(1 for s in strong_signals if s['current_price'] > s['price'])
            strong_avg_profit = sum(((s['current_price'] - s['price']) / s['price']) * 100 for s in strong_signals) / len(strong_signals)
            print(f"?“Š ê°•ë ¥??ì§„ì… ? í˜¸ ?±ê³¼: {len(strong_signals)}ê°?ì¤?{strong_profitable}ê°??˜ìµ ({strong_profitable/len(strong_signals)*100:.1f}%) | ?‰ê·  ?˜ìµë¥? {strong_avg_profit:+.2f}%")
        
        # ?µê³„ ?•ë³´
        total_coins = len(golden_cross_results)
        profitable_coins = sum(1 for r in golden_cross_results if r['current_price'] > r['price'])
        entry_profitable = sum(1 for r in entry_signals if r['current_price'] > r['price']) if entry_signals else 0
        reliable_profitable = sum(1 for r in reliable_signals if r['current_price'] > r['price']) if reliable_signals else 0
        fake_profitable = sum(1 for r in fake_signals if r['current_price'] > r['price']) if fake_signals else 0
        
        avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in golden_cross_results) / total_coins
        entry_avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in entry_signals) / len(entry_signals) if entry_signals else 0
        reliable_avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in reliable_signals) / len(reliable_signals) if reliable_signals else 0
        fake_avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in fake_signals) / len(fake_signals) if fake_signals else 0
        
        print(f"\n?“Š ê³¨ë“ ?¬ë¡œ???±ê³¼ ?µê³„:")
        print(f"   ?„ì²´ ì¢…ëª©: {total_coins}ê°?| ?˜ìµ: {profitable_coins}ê°?({profitable_coins/total_coins*100:.1f}%) | ?‰ê· : {avg_profit:+.2f}%")
        
        if entry_signals:
            print(f"   ?¯ ì§„ì… ? í˜¸: {len(entry_signals)}ê°?| ?˜ìµ: {entry_profitable}ê°?({entry_profitable/len(entry_signals)*100:.1f}%) | ?‰ê· : {entry_avg_profit:+.2f}%")
        
        if reliable_signals:
            print(f"   ?ŒŸ ? ë¢° ? í˜¸: {len(reliable_signals)}ê°?| ?˜ìµ: {reliable_profitable}ê°?({reliable_profitable/len(reliable_signals)*100:.1f}%) | ?‰ê· : {reliable_avg_profit:+.2f}%")
        
        if fake_signals:
            print(f"   ? ï¸ ?˜ì´??? í˜¸: {len(fake_signals)}ê°?| ?˜ìµ: {fake_profitable}ê°?({fake_profitable/len(fake_signals)*100:.1f}%) | ?‰ê· : {fake_avg_profit:+.2f}%")
        
        # ì§„ì… ? í˜¸ë³??±ê³¼ ë¶„ì„
        entry_types = {}
        for result in golden_cross_results:
            entry_reason = result.get('entry_reason', '?¤” ? í˜¸ ?½í•¨')
            if entry_reason not in entry_types:
                entry_types[entry_reason] = {'count': 0, 'profitable': 0, 'total_profit': 0}
            
            entry_types[entry_reason]['count'] += 1
            profit_rate = ((result['current_price'] - result['price']) / result['price']) * 100
            entry_types[entry_reason]['total_profit'] += profit_rate
            
            if result['current_price'] > result['price']:
                entry_types[entry_reason]['profitable'] += 1
        
        print(f"\n?“ˆ ì§„ì… ? í˜¸ë³??±ê³¼:")
        for entry_type, stats in entry_types.items():
            success_rate = stats['profitable'] / stats['count'] * 100
            avg_profit_type = stats['total_profit'] / stats['count']
            print(f"   {entry_type}: {stats['count']}ê°?| ?±ê³µë¥? {success_rate:.1f}% | ?‰ê· : {avg_profit_type:+.2f}%")
        
        # ìµœê³ /ìµœì? ?˜ìµë¥?        if golden_cross_results:
            best_performer = max(golden_cross_results, key=lambda x: (x['current_price'] - x['price']) / x['price'])
            worst_performer = min(golden_cross_results, key=lambda x: (x['current_price'] - x['price']) / x['price'])
            
            best_profit = ((best_performer['current_price'] - best_performer['price']) / best_performer['price']) * 100
            worst_profit = ((worst_performer['current_price'] - worst_performer['price']) / worst_performer['price']) * 100
            
            print(f"\n?† ?±ê³¼ ?œìœ„:")
            print(f"   ìµœê³  ?˜ìµ: {best_performer['coin_name']} ({best_profit:+.2f}%) - {best_performer.get('entry_reason', '')}")
            print(f"   ìµœì? ?˜ìµ: {worst_performer['coin_name']} ({worst_profit:+.2f}%) - {worst_performer.get('entry_reason', '')}")
        
        print(f"\n?’¡ ?¤ì „ ?¬ì ê°€?´ë“œ:")
        print(f"   ?? ê°•ë ¥??ì§„ì… ? í˜¸ = ê³¨ë“ ?¬ë¡œ??+ ê±°ë˜??ê¸‰ì¦ + 3-4ê°??‘ë´‰ + ?€??„  ?ŒíŒŒ")
        print(f"   ?“ˆ ì§„ì… ê³ ë ¤ = ê³¨ë“ ?¬ë¡œ??+ ê±°ë˜??ê¸‰ì¦ + 3-4ê°??‘ë´‰ ìº”ë“¤ ?•ì„±")
        print(f"   ???ŒíŒŒ ì§„ì… = ê³¨ë“ ?¬ë¡œ??+ ê±°ë˜??ê¸‰ì¦ + ?€??„  ?ŒíŒŒ")
        print(f"   ? ï¸ ?˜ì´??? í˜¸ = ê±°ë˜???†ëŠ” ê³¨ë“ ?¬ë¡œ??(?€ë¶€ë¶??¤íŒ¨)")
        print(f"   ?” ê´€ì°??„ìš” = ê±°ë˜?‰ì? ?ˆì?ë§??‘ë´‰ ìº”ë“¤???½í•œ ê²½ìš°")
        
    else:
        print(f"\n???…ë¹„????ì¢…ëª© ì¤?2???´ë‚´ ê³¨ë“ ?¬ë¡œ??ë°œìƒ ì¢…ëª©???†ìŠµ?ˆë‹¤.")

def analyze_pre_golden_cross_signals():
    """ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰ ? í˜¸ ?ì? (50MA ?°ì¹˜ ???‘ë´‰ ??200MA ?°ì¹˜ ???ìŠ¹ + ê±°ë˜??ì¦ê?)"""
    print(f"\n?¯ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰ ? í˜¸ ?ì? ?œì‘")
    print("?“‹ ?ì? ì¡°ê±´:")
    print("   1. 50MA???¿ê³  ?ˆë˜ ìº”ë“¤")
    print("   2. ?´í›„ ?‘ë´‰ ìº”ë“¤ ì¶œí˜„")
    print("   3. 200MAë¥??°ì¹˜?˜ê³  ê·??„ë¡œ ?¬ë¼ê°?)
    print("   4. ê±°ë˜?‰ì´ ?´ì „ ?€ë¹?ì¦ê?")
    print("   5. ?„ì§ ê³¨ë“ ?¬ë¡œ???´ì „ ?íƒœ (50MA < 200MA)")
    
    # ëª¨ë“  KRW ì¢…ëª© ê°€?¸ì˜¤ê¸?    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("???…ë¹„??ì¢…ëª©??ê°€?¸ì˜¬ ???†ìŠµ?ˆë‹¤.")
        return
    
    print(f"\n?“Š ì´?{len(all_tickers)}ê°?ì¢…ëª©??? í–‰ ? í˜¸ ë¶„ì„ ì¤?..")
    
    # 1???„ë????„ì¬ê¹Œì? ë¶„ì„
    one_month_ago = datetime.now() - pd.Timedelta(days=30)
    print(f"?“… ë¶„ì„ ê¸°ê°„: {one_month_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    pre_signal_results = []
    
    for i, symbol in enumerate(all_tickers[:20]):  # ì²˜ë¦¬ ?œê°„???„í•´ ?ìœ„ 20ê°œë§Œ ë¶„ì„
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"?” ë¶„ì„ ì¤?.. ({i+1}/20) {coin_name}")
        
        try:
            # 4?œê°„ ?°ì´??ì¡°íšŒ (ì¶©ë¶„???°ì´???•ë³´)
            all_data = []
            limit_per_request = 200
            total_requests = 6  # 1200ê°??°ì´??(??8ê°œì›”ì¹?
            
            for j in range(total_requests):
                try:
                    if j == 0:
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request)
                    else:
                        since = int(all_data[0][0]) - (limit_per_request * 4 * 60 * 60 * 1000)
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request, since=since)
                    
                    if data and len(data) > 0:
                        all_data = data + all_data
                    else:
                        break
                    
                    time.sleep(0.05)
                    
                except Exception as e:
                    break
            
            if not all_data:
                print(f"   ??{coin_name}: ?°ì´??ì¡°íšŒ ?¤íŒ¨")
                continue
            
            # ?°ì´?°í”„?ˆì„ ?ì„± ë°??•ì œ
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 300:
                print(f"   ? ï¸ {coin_name}: ?˜ì§‘???°ì´??ë¶€ì¡?({len(df)}ê°?")
                continue
            
            # ?°ì´???•ì œ
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 300:
                print(f"   ? ï¸ {coin_name}: ?•ì œ ???°ì´??ë¶€ì¡?)
                continue
            
            # ?´ë™?‰ê·  ê³„ì‚° (20MA, 50MA, 200MA)
            df['ma20'] = df['close'].rolling(window=20, center=False).mean()
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200??? íš¨???°ì´?°ë??°ë§Œ ?¬ìš©
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ? ï¸ {coin_name}: MA200 ê³„ì‚° ë¶ˆê?")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 1???´ë‚´ ?°ì´?°ë§Œ ?„í„°ë§?            recent_df = df_valid[df_valid['timestamp'] >= one_month_ago].copy()
            
            if len(recent_df) < 20:
                print(f"   ? ï¸ {coin_name}: 1???´ë‚´ ?°ì´??ë¶€ì¡?)
                continue
            
            # ? í–‰ ? í˜¸ ?ì?
            pre_signals = []
            
            for j in range(10, len(recent_df) - 10):  # ì¶©ë¶„???„í›„ ?°ì´???•ë³´
                curr_row = recent_df.iloc[j]
                
                # ?„ì œ ì¡°ê±´: ?„ì§ ê³¨ë“ ?¬ë¡œ???´ì „ (50MA < 200MA)
                if pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or pd.isna(curr_row['ma20']):
                    continue
                
                if curr_row['ma50'] >= curr_row['ma200']:  # ?´ë? ê³¨ë“ ?¬ë¡œ???íƒœë©??œì™¸
                    continue
                
                # ì¡°ê±´ 1: 50MA ?°ì¹˜ ?•ì¸
                ma50_touch_threshold = curr_row['ma50'] * 0.02  # 2% ?¤ì°¨ ?ˆìš©
                is_ma50_touch = (
                    abs(curr_row['low'] - curr_row['ma50']) <= ma50_touch_threshold or
                    (curr_row['low'] <= curr_row['ma50'] <= curr_row['high'])
                )
                
                if not is_ma50_touch:
                    continue
                
                # ì¡°ê±´ 2: ?´í›„ ?‘ë´‰ ìº”ë“¤ ì¶œí˜„ ?•ì¸
                bullish_found = False
                bullish_index = -1
                
                for k in range(1, min(4, len(recent_df) - j)):
                    next_candle = recent_df.iloc[j + k]
                    if next_candle['close'] > next_candle['open']:  # ?‘ë´‰
                        bullish_found = True
                        bullish_index = j + k
                        break
                
                if not bullish_found:
                    continue
                
                # ì¡°ê±´ 3: 200MA ?°ì¹˜ ???ìŠ¹ ?•ì¸
                ma200_touch_and_rise = False
                ma200_touch_index = -1
                
                for k in range(bullish_index + 1, min(bullish_index + 5, len(recent_df))):
                    check_candle = recent_df.iloc[k]
                    
                    if pd.isna(check_candle['ma200']):
                        continue
                    
                    # 200MA ?°ì¹˜ ?•ì¸
                    ma200_touch_threshold = check_candle['ma200'] * 0.015  # 1.5% ?¤ì°¨ ?ˆìš©
                    is_ma200_touch = (
                        abs(check_candle['low'] - check_candle['ma200']) <= ma200_touch_threshold or
                        (check_candle['low'] <= check_candle['ma200'] <= check_candle['high'])
                    )
                    
                    if is_ma200_touch:
                        # ?°ì¹˜ ???ìŠ¹ ?•ì¸
                        if k + 1 < len(recent_df):
                            next_candle = recent_df.iloc[k + 1]
                            if next_candle['close'] > check_candle['ma200']:
                                ma200_touch_and_rise = True
                                ma200_touch_index = k
                                break
                
                if not ma200_touch_and_rise:
                    continue
                
                # ì¡°ê±´ 4: ê±°ë˜??ì¦ê? ?•ì¸
                volume_surge = False
                if j >= 10:
                    prev_volumes = [recent_df.iloc[j - k]['volume'] for k in range(1, 11)]
                    avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
                    
                    signal_volume = recent_df.iloc[ma200_touch_index]['volume']
                    if signal_volume > avg_prev_volume * 1.3:  # 1.3ë°??´ìƒ
                        volume_surge = True
                
                if not volume_surge:
                    continue
                
                # ëª¨ë“  ì¡°ê±´??ë§Œì¡±?˜ëŠ” ? í˜¸ ë°œê²¬!
                signal_candle = recent_df.iloc[ma200_touch_index]
                days_ago = (datetime.now() - signal_candle['timestamp'].to_pydatetime()).days
                
                # ?„ì¬ê°€ ì¡°íšŒ
                current_price = get_current_price(symbol)
                if current_price is None:
                    current_price = recent_df.iloc[-1]['close']
                
                # ? í˜¸ ?´í›„ ?˜ìµë¥?ê³„ì‚°
                profit_rate = ((current_price - signal_candle['close']) / signal_candle['close']) * 100
                
                pre_signals.append({
                    'symbol': symbol,
                    'coin_name': coin_name,
                    'signal_date': signal_candle['timestamp'],
                    'days_ago': days_ago,
                    'signal_price': signal_candle['close'],
                    'current_price': current_price,
                    'profit_rate': profit_rate,
                    'ma20': signal_candle['ma20'],
                    'ma50': signal_candle['ma50'],
                    'ma200': signal_candle['ma200'],
                    'volume_ratio': signal_candle['volume'] / avg_prev_volume,
                    'ma50_touch_date': curr_row['timestamp'],
                    'bullish_date': recent_df.iloc[bullish_index]['timestamp']
                })
            
            if pre_signals:
                # ê°€??ìµœê·¼ ? í˜¸ë§??€??                latest_signal = pre_signals[-1]
                pre_signal_results.append(latest_signal)
                print(f"   ??{coin_name}: {latest_signal['days_ago']}????? í–‰? í˜¸ ({latest_signal['profit_rate']:+.1f}%)")
            else:
                print(f"   ??{coin_name}: 1???´ë‚´ ? í–‰? í˜¸ ?†ìŒ")
        
        except Exception as e:
            print(f"   ??{coin_name}: ë¶„ì„ ?¤íŒ¨ - {e}")
            continue
        
        # API ?”ì²­ ?œí•œ ë°©ì?
        time.sleep(0.05)
    
    if not pre_signal_results:
        print("\n??1???´ë‚´ ? í–‰? í˜¸ë¥?ë°œê²¬??ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        print("?’¡ ì¡°ê±´???„í™”?˜ê±°??ë¶„ì„ ê¸°ê°„???˜ë ¤ë³´ì„¸??")
        return pre_signal_results
    
    # ê²°ê³¼ ?•ë ¬ (?˜ìµë¥?ê¸°ì? ?´ë¦¼ì°¨ìˆœ)
    pre_signal_results.sort(key=lambda x: x['profit_rate'], reverse=True)
    
    # ê²°ê³¼ ì¶œë ¥
    print(f"\n?“Š ? í–‰? í˜¸ ë¶„ì„ ê²°ê³¼ ({len(pre_signal_results)}ê°?ì¢…ëª©)")
    print("=" * 140)
    print(f"{'?œìœ„':<4} {'ì¢…ëª©':<8} {'? í˜¸??:<12} {'?¼ìˆ˜':<6} {'? í˜¸ê°€ê²?:<12} {'?„ì¬ê°€':<12} {'?˜ìµë¥?:<8} {'ê±°ë˜?‰ë¹„??:<10} {'MA50':<10} {'MA200':<10}")
    print("-" * 140)
    
    for i, signal in enumerate(pre_signal_results):
        rank = i + 1
        coin_name = signal['coin_name']
        signal_date = signal['signal_date'].strftime('%m-%d')
        days_ago = f"{signal['days_ago']}??
        signal_price = f"{signal['signal_price']:,.0f}??
        current_price = f"{signal['current_price']:,.0f}??
        profit_rate = f"{signal['profit_rate']:+.1f}%"
        volume_ratio = f"{signal['volume_ratio']:.1f}x"
        ma50 = f"{signal['ma50']:,.0f}??
        ma200 = f"{signal['ma200']:,.0f}??
        
        # ?˜ìµë¥ ì— ?°ë¥¸ ?´ëª¨ì§€
        profit_emoji = "?“ˆ" if signal['profit_rate'] > 0 else "?“‰"
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {days_ago:<6} {signal_price:<12} {current_price:<12} {profit_emoji}{profit_rate:<7} {volume_ratio:<10} {ma50:<10} {ma200:<10}")
    
    print("-" * 140)
    
    # ?µê³„ ?•ë³´
    total_signals = len(pre_signal_results)
    profitable_signals = sum(1 for s in pre_signal_results if s['profit_rate'] > 0)
    avg_profit = sum(s['profit_rate'] for s in pre_signal_results) / total_signals
    
    print(f"\n?“ˆ ? í–‰? í˜¸ ?±ê³¼ ?µê³„:")
    print(f"   ?„ì²´ ? í˜¸: {total_signals}ê°?)
    print(f"   ?˜ìµ ? í˜¸: {profitable_signals}ê°?({profitable_signals/total_signals*100:.1f}%)")
    print(f"   ?‰ê·  ?˜ìµë¥? {avg_profit:+.2f}%")
    
    if profitable_signals > 0:
        profitable_avg = sum(s['profit_rate'] for s in pre_signal_results if s['profit_rate'] > 0) / profitable_signals
        print(f"   ?˜ìµ ? í˜¸ ?‰ê· : {profitable_avg:+.2f}%")
    
    # ìµœê³ /ìµœì? ?˜ìµë¥?    if pre_signal_results:
        best_signal = max(pre_signal_results, key=lambda x: x['profit_rate'])
        worst_signal = min(pre_signal_results, key=lambda x: x['profit_rate'])
        
        print(f"\n?† ?±ê³¼ ?œìœ„:")
        print(f"   ìµœê³  ?˜ìµ: {best_signal['coin_name']} ({best_signal['profit_rate']:+.2f}%) - {best_signal['days_ago']}????)
        print(f"   ìµœì? ?˜ìµ: {worst_signal['coin_name']} ({worst_signal['profit_rate']:+.2f}%) - {worst_signal['days_ago']}????)
    
    print(f"\n?’¡ ? í–‰? í˜¸ ?¬ì ê°€?´ë“œ:")
    print(f"   ?¯ 50MA ?°ì¹˜ ???‘ë´‰ ??200MA ?°ì¹˜ ???ìŠ¹ + ê±°ë˜??ì¦ê? ?¨í„´")
    print(f"   ?“Š ê±°ë˜??1.3ë°??´ìƒ ì¦ê? ??? ë¢°???’ìŒ")
    print(f"   ?? ê³¨ë“ ?¬ë¡œ???´ì „ ?¨ê³„?ì„œ ë¯¸ë¦¬ ?¬ì°© ê°€??)
    print(f"   ? ï¸ ?„ì§ ê³¨ë“ ?¬ë¡œ???´ì „?´ë?ë¡?ì¶”ê? ?•ì¸ ?„ìš”")
    
    return pre_signal_results

def analyze_recent_pre_signals():
    """3???´ë‚´ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ê¸´ê¸‰ ë¶„ì„"""
    print(f"\n?š¨ 3???´ë‚´ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ê¸´ê¸‰ ë¶„ì„")
    print("?“‹ ë¶„ì„ ëª©ì : ê³¨ë“ ?¬ë¡œ???„ë°• ì¢…ëª© ?¤ì‹œê°?ëª¨ë‹ˆ?°ë§")
    print("?” ë¶„ì„ ì¡°ê±´:")
    print("   1. ìµœê·¼ 3???´ë‚´ ? í–‰? í˜¸ ë°œìƒ")
    print("   2. ?„ì¬ 50MA?€ 200MA ê°„ê²©??5% ?´ë‚´ (ê³¨ë“ ?¬ë¡œ???„ë°•)")
    print("   3. ê±°ë˜??ì¦ê? ?™ë°˜")
    
    # ëª¨ë“  KRW ì¢…ëª© ê°€?¸ì˜¤ê¸?    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("???…ë¹„??ì¢…ëª©??ê°€?¸ì˜¬ ???†ìŠµ?ˆë‹¤.")
        return
    
    print(f"\n?“Š ì´?{len(all_tickers)}ê°?ì¢…ëª©??ê¸´ê¸‰ ë¶„ì„ ì¤?..")
    
    # 3???„ë????„ì¬ê¹Œì? ë¶„ì„
    three_days_ago = datetime.now() - pd.Timedelta(days=3)
    print(f"?“… ë¶„ì„ ê¸°ê°„: {three_days_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    recent_signals = []
    
    for i, symbol in enumerate(all_tickers[:30]):  # ?ìœ„ 30ê°?ë¶„ì„
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"?” ê¸´ê¸‰ ë¶„ì„ ì¤?.. ({i+1}/30) {coin_name}")
        
        try:
            # 1?œê°„ ?°ì´??ì¡°íšŒ (???¸ë???ë¶„ì„)
            all_data = []
            limit_per_request = 200
            total_requests = 4  # 800ê°??°ì´??(??1ê°œì›”ì¹?
            
            for j in range(total_requests):
                try:
                    if j == 0:
                        data = upbit.fetch_ohlcv(symbol, timeframe='1h', limit=limit_per_request)
                    else:
                        since = int(all_data[0][0]) - (limit_per_request * 60 * 60 * 1000)
                        data = upbit.fetch_ohlcv(symbol, timeframe='1h', limit=limit_per_request, since=since)
                    
                    if data and len(data) > 0:
                        all_data = data + all_data
                    else:
                        break
                    
                    time.sleep(0.03)
                    
                except Exception as e:
                    break
            
            if not all_data:
                print(f"   ??{coin_name}: ?°ì´??ì¡°íšŒ ?¤íŒ¨")
                continue
            
            # ?°ì´?°í”„?ˆì„ ?ì„± ë°??•ì œ
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 250:
                print(f"   ? ï¸ {coin_name}: ?˜ì§‘???°ì´??ë¶€ì¡?({len(df)}ê°?")
                continue
            
            # ?°ì´???•ì œ
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            # ?´ë™?‰ê·  ê³„ì‚°
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200??? íš¨???°ì´?°ë??°ë§Œ ?¬ìš©
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ? ï¸ {coin_name}: MA200 ê³„ì‚° ë¶ˆê?")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # ?„ì¬ ?íƒœ ?•ì¸
            latest = df_valid.iloc[-1]
            
            # ê³¨ë“ ?¬ë¡œ???„ë°•???•ì¸ (50MA?€ 200MA ê°„ê²©??5% ?´ë‚´)
            if pd.isna(latest['ma50']) or pd.isna(latest['ma200']):
                print(f"   ? ï¸ {coin_name}: MA ê°?ê³„ì‚° ë¶ˆê?")
                continue
            
            ma_gap_percent = abs(latest['ma50'] - latest['ma200']) / latest['ma200'] * 100
            
            if ma_gap_percent > 5:  # 5% ì´ˆê³¼?˜ë©´ ê³¨ë“ ?¬ë¡œ???„ë°•?˜ì? ?ŠìŒ
                print(f"   ??{coin_name}: MA ê°„ê²© {ma_gap_percent:.1f}% (?„ê³„ê°?5% ì´ˆê³¼)")
                continue
            
            # ?„ì§ ê³¨ë“ ?¬ë¡œ???´ì „ ?íƒœ?¸ì? ?•ì¸
            if latest['ma50'] >= latest['ma200']:
                print(f"   ??{coin_name}: ?´ë? ê³¨ë“ ?¬ë¡œ???íƒœ")
                continue
            
            # 3???´ë‚´ ?°ì´?°ë§Œ ?„í„°ë§?            recent_df = df_valid[df_valid['timestamp'] >= three_days_ago].copy()
            
            if len(recent_df) < 10:
                print(f"   ? ï¸ {coin_name}: 3???´ë‚´ ?°ì´??ë¶€ì¡?)
                continue
            
            # ìµœê·¼ ê±°ë˜??ì¦ê? ?•ì¸
            if len(recent_df) >= 20:
                recent_volume_avg = recent_df.tail(10)['volume'].mean()
                prev_volume_avg = recent_df.head(10)['volume'].mean()
                volume_increase_ratio = recent_volume_avg / prev_volume_avg if prev_volume_avg > 0 else 1
            else:
                volume_increase_ratio = 1
            
            # ê³¨ë“ ?¬ë¡œ???„ë°•???ìˆ˜ ê³„ì‚°
            proximity_score = max(0, 100 - (ma_gap_percent * 20))  # ê°„ê²©??ì¢ì„?˜ë¡ ?’ì? ?ìˆ˜
            
            # ?„ì¬ê°€ ì¡°íšŒ
            current_price = get_current_price(symbol)
            if current_price is None:
                current_price = latest['close']
            
            recent_signals.append({
                'coin_name': coin_name,
                'symbol': symbol,
                'current_price': current_price,
                'ma50': latest['ma50'],
                'ma200': latest['ma200'],
                'ma_gap_percent': ma_gap_percent,
                'proximity_score': proximity_score,
                'volume_increase_ratio': volume_increase_ratio,
                'latest_timestamp': latest['timestamp']
            })
            
            print(f"   ?¯ {coin_name}: ê³¨ë“ ?¬ë¡œ???„ë°•??{proximity_score:.0f}??(MAê°„ê²© {ma_gap_percent:.1f}%)")
            
        except Exception as e:
            print(f"   ??{coin_name}: ë¶„ì„ ?¤íŒ¨ - {e}")
            continue
        
        time.sleep(0.03)
    
    if not recent_signals:
        print("\n??3???´ë‚´ ê³¨ë“ ?¬ë¡œ???„ë°• ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        print("?’¡ ?œì¥???ˆì •?ì´ê±°ë‚˜ ?€ë¶€ë¶?ì¢…ëª©???´ë? ê³¨ë“ ?¬ë¡œ?¤ë? ì§€?¬ì„ ???ˆìŠµ?ˆë‹¤.")
        return recent_signals
    
    # ê³¨ë“ ?¬ë¡œ???„ë°•???œìœ¼ë¡??•ë ¬
    recent_signals.sort(key=lambda x: x['proximity_score'], reverse=True)
    
    # ê²°ê³¼ ì¶œë ¥
    print(f"\n?š¨ ê³¨ë“ ?¬ë¡œ???„ë°• ì¢…ëª© ({len(recent_signals)}ê°?")
    print("=" * 120)
    print(f"{'?œìœ„':<4} {'ì¢…ëª©':<8} {'?„ë°•??:<8} {'MAê°„ê²©':<8} {'?„ì¬ê°€':<12} {'MA50':<12} {'MA200':<12} {'ê±°ë˜?‰ì¦ê°€':<10}")
    print("-" * 120)
    
    for i, signal in enumerate(recent_signals):
        rank = i + 1
        coin_name = signal['coin_name']
        proximity_score = f"{signal['proximity_score']:.0f}??
        ma_gap = f"{signal['ma_gap_percent']:.1f}%"
        current_price = f"{signal['current_price']:,.0f}??
        ma50 = f"{signal['ma50']:,.0f}??
        ma200 = f"{signal['ma200']:,.0f}??
        volume_ratio = f"{signal['volume_increase_ratio']:.1f}x"
        
        # ?„ë°•?„ì— ?°ë¥¸ ?´ëª¨ì§€
        if signal['proximity_score'] >= 80:
            urgency_emoji = "?”¥"
        elif signal['proximity_score'] >= 60:
            urgency_emoji = "?¯"
        else:
            urgency_emoji = "? ï¸"
        
        print(f"{urgency_emoji}{rank:<3} {coin_name:<8} {proximity_score:<8} {ma_gap:<8} {current_price:<12} {ma50:<12} {ma200:<12} {volume_ratio:<10}")
    
    print("-" * 120)
    
    # ê¸´ê¸‰ ëª¨ë‹ˆ?°ë§ ?€??(?ìœ„ 5ê°?
    top_urgent = recent_signals[:5]
    
    print(f"\n?”¥ ê¸´ê¸‰ ëª¨ë‹ˆ?°ë§ ?€??(?ìœ„ 5ê°?")
    print("=" * 100)
    
    for i, signal in enumerate(top_urgent):
        rank = i + 1
        coin_name = signal['coin_name']
        proximity_score = signal['proximity_score']
        ma_gap = signal['ma_gap_percent']
        
        print(f"{rank}. ?š¨ {coin_name}: ?„ë°•??{proximity_score:.0f}??(MAê°„ê²© {ma_gap:.1f}%)")
        print(f"   ?’° ?„ì¬ê°€: {signal['current_price']:,.0f}??)
        print(f"   ?“ˆ MA50: {signal['ma50']:,.0f}??| MA200: {signal['ma200']:,.0f}??)
        print(f"   ?“Š ê±°ë˜??ì¦ê?: {signal['volume_increase_ratio']:.1f}ë°?)
        print()
    
    print(f"?’¡ ê¸´ê¸‰ ëª¨ë‹ˆ?°ë§ ê°€?´ë“œ:")
    print(f"   ?”¥ ?„ë°•??80???´ìƒ: 24?œê°„ ??ê³¨ë“ ?¬ë¡œ??ê°€?¥ì„± ?’ìŒ")
    print(f"   ?¯ ?„ë°•??60-79?? 2-3????ê³¨ë“ ?¬ë¡œ??ê°€?¥ì„±")
    print(f"   ? ï¸ ?„ë°•??60??ë¯¸ë§Œ: 1ì£¼ì¼ ??ê³¨ë“ ?¬ë¡œ??ê°€?¥ì„±")
    print(f"   ?“Š ê±°ë˜??1.5ë°??´ìƒ ì¦ê? ??? í˜¸ ê°•í™”")
    
    return recent_signals

def analyze_high_profit_patterns():
    """ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„ (ì°¨íŠ¸ ì§€??ê³µí†µ??ë°œêµ´)"""
    print(f"\n?“Š ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„")
    print("?“‹ ë¶„ì„ ëª©ì : ìµœê·¼ 2?¬ê°„ ?’ì? ?˜ìµë¥ ì„ ê¸°ë¡??ì¢…ëª©?¤ì˜ ì°¨íŠ¸ ì§€??ê³µí†µ??ë°œêµ´")
    print("?” ë¶„ì„ ?€?? ê³¨ë“ ?¬ë¡œ??ë°œìƒ ??20% ?´ìƒ ?˜ìµë¥ ì„ ê¸°ë¡??ì¢…ëª©")
    
    # ë¨¼ì? 2???´ë‚´ ê³¨ë“ ?¬ë¡œ??ë¶„ì„ ?¤í–‰
    print("\n?” 1?¨ê³„: 2???´ë‚´ ê³¨ë“ ?¬ë¡œ??ì¢…ëª© ?˜ì§‘ ì¤?..")
    golden_cross_results = analyze_all_coins_golden_cross()
    
    if not golden_cross_results:
        print("??ë¶„ì„??ê³¨ë“ ?¬ë¡œ??ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        return
    
    # ê³ ìˆ˜??ì¢…ëª© ?„í„°ë§?(20% ?´ìƒ)
    high_profit_threshold = 20.0
    high_profit_coins = []
    
    for result in golden_cross_results:
        profit_rate = ((result['current_price'] - result['price']) / result['price']) * 100
        if profit_rate >= high_profit_threshold:
            result['profit_rate'] = profit_rate
            high_profit_coins.append(result)
    
    if not high_profit_coins:
        print(f"??{high_profit_threshold}% ?´ìƒ ?˜ìµë¥ ì„ ê¸°ë¡??ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        print("?’¡ ?˜ìµë¥?ê¸°ì?????¶°???¤ì‹œ ë¶„ì„?´ë³´?¸ìš”.")
        return
    
    print(f"\n?“ˆ 2?¨ê³„: {len(high_profit_coins)}ê°?ê³ ìˆ˜??ì¢…ëª©??ì°¨íŠ¸ ì§€??ë¶„ì„")
    print("=" * 120)
    
    detailed_analysis = []
    
    for i, coin_data in enumerate(high_profit_coins):
        symbol = coin_data['symbol']
        coin_name = coin_data['coin_name']
        profit_rate = coin_data['profit_rate']
        
        print(f"?” ë¶„ì„ ì¤?.. ({i+1}/{len(high_profit_coins)}) {coin_name} ({profit_rate:+.1f}%)")
        
        try:
            # ê³¨ë“ ?¬ë¡œ???œì  ê¸°ì??¼ë¡œ ?°ì´???˜ì§‘
            signal_date = coin_data['date']
            
            # ì¶©ë¶„???°ì´???˜ì§‘
            all_data = []
            limit_per_request = 200
            total_requests = 6  # 1200ê°??°ì´??            
            for j in range(total_requests):
                try:
                    if j == 0:
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request)
                    else:
                        since = int(all_data[0][0]) - (limit_per_request * 4 * 60 * 60 * 1000)
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request, since=since)
                    
                    if data and len(data) > 0:
                        all_data = data + all_data
                    else:
                        break
                    
                    time.sleep(0.03)
                    
                except Exception as e:
                    break
            
            if not all_data or len(all_data) < 300:
                print(f"   ? ï¸ {coin_name}: ?°ì´??ë¶€ì¡?)
                continue
            
            # ?°ì´?°í”„?ˆì„ ?ì„±
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0].reset_index(drop=True)
            
            # ê¸°ìˆ ??ì§€??ê³„ì‚°
            df['ma20'] = df['close'].rolling(window=20).mean()
            df['ma50'] = df['close'].rolling(window=50).mean()
            df['ma200'] = df['close'].rolling(window=200).mean()
            
            # RSI ê³„ì‚°
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # ë³¼ë¦°?€ ë°´ë“œ ê³„ì‚°
            df['bb_middle'] = df['close'].rolling(window=20).mean()
            bb_std = df['close'].rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
            
            # MACD ê³„ì‚°
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            
            # ê±°ë˜??ì§€??            df['volume_ma20'] = df['volume'].rolling(window=20).mean()
            df['volume_ratio'] = df['volume'] / df['volume_ma20']
            
            # ë³€?™ì„± ì§€??            df['volatility'] = df['close'].rolling(window=20).std() / df['close'].rolling(window=20).mean()
            
            # ê³¨ë“ ?¬ë¡œ???œì  ì°¾ê¸°
            signal_idx = None
            for idx, row in df.iterrows():
                if abs((row['timestamp'] - signal_date).total_seconds()) < 7200:  # 2?œê°„ ?¤ì°¨ ?ˆìš©
                    signal_idx = idx
                    break
            
            if signal_idx is None or signal_idx < 50:
                print(f"   ? ï¸ {coin_name}: ê³¨ë“ ?¬ë¡œ???œì  ì°¾ê¸° ?¤íŒ¨")
                continue
            
            # ê³¨ë“ ?¬ë¡œ???œì ??ì§€??ê°’ë“¤
            signal_row = df.iloc[signal_idx]
            
            analysis_data = {
                'coin_name': coin_name,
                'symbol': symbol,
                'profit_rate': profit_rate,
                'signal_date': signal_date,
                'rsi': signal_row['rsi'],
                'bb_position': signal_row['bb_position'],
                'macd': signal_row['macd'],
                'macd_signal': signal_row['macd_signal'],
                'volume_ratio': signal_row['volume_ratio'],
                'volatility': signal_row['volatility'],
                'ma20': signal_row['ma20'],
                'ma50': signal_row['ma50'],
                'ma200': signal_row['ma200']
            }
            
            detailed_analysis.append(analysis_data)
            
            print(f"   ??{coin_name}: RSI {signal_row['rsi']:.1f}, BB?„ì¹˜ {signal_row['bb_position']:.2f}, ê±°ë˜??{signal_row['volume_ratio']:.1f}x")
            
        except Exception as e:
            print(f"   ??{coin_name}: ë¶„ì„ ?¤íŒ¨ - {e}")
            continue
        
        time.sleep(0.05)
    
    if not detailed_analysis:
        print("???ì„¸ ë¶„ì„???°ì´?°ê? ?†ìŠµ?ˆë‹¤.")
        return
    
    # 3?¨ê³„: ê³µí†µ ?¨í„´ ë¶„ì„
    print(f"\n?¯ 3?¨ê³„: ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ë¶„ì„")
    print("=" * 120)
    
    # ?‰ê· ê°?ê³„ì‚°
    avg_rsi = sum(a['rsi'] for a in detailed_analysis if not pd.isna(a['rsi'])) / len([a for a in detailed_analysis if not pd.isna(a['rsi'])])
    avg_bb_pos = sum(a['bb_position'] for a in detailed_analysis if not pd.isna(a['bb_position'])) / len([a for a in detailed_analysis if not pd.isna(a['bb_position'])])
    avg_macd = sum(a['macd'] for a in detailed_analysis if not pd.isna(a['macd'])) / len([a for a in detailed_analysis if not pd.isna(a['macd'])])
    avg_volume_ratio = sum(a['volume_ratio'] for a in detailed_analysis if not pd.isna(a['volume_ratio'])) / len([a for a in detailed_analysis if not pd.isna(a['volume_ratio'])])
    avg_volatility = sum(a['volatility'] for a in detailed_analysis if not pd.isna(a['volatility'])) / len([a for a in detailed_analysis if not pd.isna(a['volatility'])])
    
    print(f"?“Š ê³ ìˆ˜??ì¢…ëª© ê³µí†µ ?¨í„´:")
    print(f"   ?“ˆ ?‰ê·  RSI: {avg_rsi:.1f}")
    print(f"   ?“Š ?‰ê·  ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜: {avg_bb_pos:.2f} (0.5 = ì¤‘ì•™??")
    print(f"   ?“‰ ?‰ê·  MACD: {avg_macd:.4f}")
    print(f"   ?“Š ?‰ê·  ê±°ë˜??ë¹„ìœ¨: {avg_volume_ratio:.1f}ë°?)
    print(f"   ?“ˆ ?‰ê·  ë³€?™ì„±: {avg_volatility:.3f}")
    
    # ?ì„¸ ê²°ê³¼ ?Œì´ë¸?    print(f"\n?“‹ ê³ ìˆ˜??ì¢…ëª© ?ì„¸ ë¶„ì„ ê²°ê³¼")
    print("=" * 140)
    print(f"{'ì¢…ëª©':<8} {'?˜ìµë¥?:<8} {'RSI':<6} {'BB?„ì¹˜':<8} {'MACD':<8} {'ê±°ë˜??:<8} {'?‘ë´‰ë¥?:<8} {'ë³€?™ì„±':<8}")
    print("-" * 140)
    
    # ?˜ìµë¥??œìœ¼ë¡??•ë ¬
    detailed_analysis.sort(key=lambda x: x['profit_rate'], reverse=True)
    
    for analysis in detailed_analysis:
        coin_name = analysis['coin_name']
        profit_rate = f"{analysis['profit_rate']:+.1f}%"
        rsi = f"{analysis['rsi']:.0f}" if not pd.isna(analysis['rsi']) else "N/A"
        bb_pos = f"{analysis['bb_position']:.2f}" if not pd.isna(analysis['bb_position']) else "N/A"
        macd = f"{analysis['macd']:.3f}" if not pd.isna(analysis['macd']) else "N/A"
        volume = f"{analysis['volume_ratio']:.1f}x" if not pd.isna(analysis['volume_ratio']) else "N/A"
        bullish = "N/A"  # ì¶”í›„ ê³„ì‚° ê°€??        volatility = f"{analysis['volatility']:.3f}" if not pd.isna(analysis['volatility']) else "N/A"
        
        print(f"{coin_name:<8} {profit_rate:<8} {rsi:<6} {bb_pos:<8} {macd:<8} {volume:<8} {bullish:<8} {volatility:<8}")
    
    return detailed_analysis

def analyze_pattern_matching():
    """1ë²?? í–‰? í˜¸ ë¶„ì„ ê¸°ë°˜ ?¼ì£¼????ìµœê³  ?˜ìµë¥?ì¢…ëª© ?¨í„´ ì¶”ì¶œ"""
    print(f"\n?¯ ? í–‰? í˜¸ ê¸°ë°˜ ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„")
    print("?“‹ ë¶„ì„ ëª©ì : 1ë²?? í–‰? í˜¸ ë¶„ì„ ì¢…ëª©??ì¤??¼ì£¼????ìµœê³  ?˜ìµë¥ ì„ ê¸°ë¡??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ì¶”ì¶œ")
    print("?” ë¶„ì„ ê³¼ì •:")
    print("   1. 1ë²?? í–‰? í˜¸ ë¶„ì„ ?¤í–‰")
    print("   2. ê°?ì¢…ëª©??? í–‰? í˜¸ ë°œìƒ ???¼ì£¼????ìµœê³  ?˜ìµë¥?ê³„ì‚°")
    print("   3. ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ì¶”ì¶œ")
    print("   4. ?¨í„´ ê¸°ë°˜ ?¬ì ê°€?´ë“œ?¼ì¸ ?œì‹œ")
    
    # 1?¨ê³„: 1ë²?? í–‰? í˜¸ ë¶„ì„ ?¤í–‰
    print("\n?” 1?¨ê³„: ? í–‰? í˜¸ ë¶„ì„ ?¤í–‰ ì¤?..")
    pre_signal_results = analyze_pre_golden_cross_signals()
    
    if not pre_signal_results:
        print("??? í–‰? í˜¸ë¥?ë°œê²¬??ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        return
    
    # 2?¨ê³„: ?¼ì£¼????ìµœê³  ?˜ìµë¥?ê³„ì‚°
    print(f"\n?“Š 2?¨ê³„: {len(pre_signal_results)}ê°?? í–‰? í˜¸ ì¢…ëª©???¼ì£¼?????˜ìµë¥?ë¶„ì„")
    print("=" * 150)
    
    enhanced_results = []
    
    for i, signal in enumerate(pre_signal_results):
        symbol = signal['symbol']
        coin_name = signal['coin_name']
        signal_date = signal['signal_date']
        signal_price = signal['signal_price']
        
        print(f"?” ?¼ì£¼???˜ìµë¥?ë¶„ì„ ì¤?.. ({i+1}/{len(pre_signal_results)}) {coin_name}")
        
        try:
            # ? í˜¸ ë°œìƒ ???¼ì£¼?¼ê°„???°ì´???˜ì§‘
            one_week_later = signal_date + pd.Timedelta(days=7)
            
            # 1?œê°„ ?°ì´?°ë¡œ ???•ë???ë¶„ì„
            data = upbit.fetch_ohlcv(symbol, timeframe='1h', limit=200)
            
            if not data:
                print(f"   ??{coin_name}: ?°ì´??ì¡°íšŒ ?¤íŒ¨")
                continue
            
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # ? í˜¸ ë°œìƒ ???¼ì£¼?¼ê°„???°ì´???„í„°ë§?            week_data = df[
                (df['timestamp'] > signal_date) & 
                (df['timestamp'] <= one_week_later)
            ]
            
            if len(week_data) == 0:
                print(f"   ??{coin_name}: ?¼ì£¼???°ì´???†ìŒ")
                continue
            
            # ?¼ì£¼????ìµœê³ ê°€ ì°¾ê¸°
            max_price_in_week = week_data['high'].max()
            max_profit_rate = ((max_price_in_week - signal_price) / signal_price) * 100
            
            # ê¸°ìˆ ??ì§€??ê³„ì‚° (? í˜¸ ë°œìƒ ?œì )
            # ??ë§ì? ?°ì´?°ë¡œ ì§€??ê³„ì‚°
            extended_data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=300)
            if extended_data:
                ext_df = pd.DataFrame(extended_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                ext_df['timestamp'] = pd.to_datetime(ext_df['timestamp'], unit='ms')
                
                # RSI ê³„ì‚°
                delta = ext_df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                ext_df['rsi'] = 100 - (100 / (1 + rs))
                
                # ë³¼ë¦°?€ ë°´ë“œ ê³„ì‚°
                ext_df['bb_middle'] = ext_df['close'].rolling(window=20).mean()
                bb_std = ext_df['close'].rolling(window=20).std()
                ext_df['bb_upper'] = ext_df['bb_middle'] + (bb_std * 2)
                ext_df['bb_lower'] = ext_df['bb_middle'] - (bb_std * 2)
                ext_df['bb_position'] = (ext_df['close'] - ext_df['bb_lower']) / (ext_df['bb_upper'] - ext_df['bb_lower'])
                
                # MACD ê³„ì‚°
                exp1 = ext_df['close'].ewm(span=12).mean()
                exp2 = ext_df['close'].ewm(span=26).mean()
                ext_df['macd'] = exp1 - exp2
                ext_df['macd_signal'] = ext_df['macd'].ewm(span=9).mean()
                
                # ? í˜¸ ë°œìƒ ?œì ê³?ê°€??ê°€ê¹Œìš´ ?°ì´??ì°¾ê¸°
                signal_row = None
                min_time_diff = float('inf')
                
                for _, row in ext_df.iterrows():
                    time_diff = abs((row['timestamp'] - signal_date).total_seconds())
                    if time_diff < min_time_diff:
                        min_time_diff = time_diff
                        signal_row = row
                
                if signal_row is not None:
                    enhanced_signal = signal.copy()
                    enhanced_signal.update({
                        'max_price_in_week': max_price_in_week,
                        'max_profit_rate': max_profit_rate,
                        'rsi': signal_row['rsi'],
                        'bb_position': signal_row['bb_position'],
                        'macd': signal_row['macd'],
                        'macd_signal': signal_row['macd_signal']
                    })
                    
                    enhanced_results.append(enhanced_signal)
                    print(f"   ??{coin_name}: ?¼ì£¼??ìµœê³  ?˜ìµë¥?{max_profit_rate:.1f}%")
                else:
                    print(f"   ? ï¸ {coin_name}: ? í˜¸ ?œì  ?°ì´??ë§¤ì¹­ ?¤íŒ¨")
            else:
                print(f"   ??{coin_name}: ?•ì¥ ?°ì´??ì¡°íšŒ ?¤íŒ¨")
                
        except Exception as e:
            print(f"   ??{coin_name}: ë¶„ì„ ?¤íŒ¨ - {e}")
            continue
        
        time.sleep(0.05)
    
    if not enhanced_results:
        print("???¼ì£¼???˜ìµë¥?ë¶„ì„???°ì´?°ê? ?†ìŠµ?ˆë‹¤.")
        return
    
    # ?¼ì£¼????ìµœê³  ?˜ìµë¥?ê¸°ì??¼ë¡œ ?•ë ¬
    enhanced_results.sort(key=lambda x: x['max_profit_rate'], reverse=True)
    
    # ?ìœ„ ?˜ìµë¥?ì¢…ëª©??ì¶œë ¥
    print(f"{'?œìœ„':<4} {'ì¢…ëª©':<8} {'? í˜¸??:<12} {'? í˜¸ê°€ê²?:<12} {'?¼ì£¼?¼ìµœê³ ê?':<15} {'ìµœê³ ?˜ìµë¥?:<12} {'?„ì¬?˜ìµë¥?:<12}")
    print("-" * 150)
    
    for i, signal in enumerate(enhanced_results):
        rank = i + 1
        coin_name = signal['coin_name']
        signal_date = signal['signal_date'].strftime('%m-%d')
        signal_price = f"{signal['signal_price']:,.0f}??
        max_price = f"{signal['max_price_in_week']:,.0f}??
        max_profit = f"{signal['max_profit_rate']:+.1f}%"
        current_profit = f"{signal['profit_rate']:+.1f}%"
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {signal_price:<12} {max_price:<15} {max_profit:<12} {current_profit:<12}")
    
    # 3?¨ê³„: ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ì¶”ì¶œ
    print(f"\n?¯ 3?¨ê³„: ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ì¶”ì¶œ")
    print("=" * 120)
    
    # ?ìœ„ 30% ì¢…ëª©??ê³ ìˆ˜??ê·¸ë£¹?¼ë¡œ ë¶„ë¥˜
    top_30_percent_count = max(1, len(enhanced_results) // 3)
    high_profit_signals = enhanced_results[:top_30_percent_count]
    low_profit_signals = enhanced_results[top_30_percent_count:]
    
    print(f"?“ˆ ê³ ìˆ˜??ê·¸ë£¹: ?ìœ„ {top_30_percent_count}ê°?ì¢…ëª© (?‰ê·  ?˜ìµë¥? {sum(s['max_profit_rate'] for s in high_profit_signals) / len(high_profit_signals):.1f}%)")
    print(f"?“‰ ?¼ë°˜ ê·¸ë£¹: ?˜ë¨¸ì§€ {len(low_profit_signals)}ê°?ì¢…ëª© (?‰ê·  ?˜ìµë¥? {sum(s['max_profit_rate'] for s in low_profit_signals) / len(low_profit_signals):.1f}%)")
    
    # ?¨í„´ ë¶„ì„ ?¨ìˆ˜
    def analyze_pattern_differences(high_group, low_group, pattern_name, value_key):
        if not high_group or not low_group:
            return
        
        # NaN ê°??œê±°
        high_values = [s[value_key] for s in high_group if not pd.isna(s[value_key])]
        low_values = [s[value_key] for s in low_group if not pd.isna(s[value_key])]
        
        if not high_values or not low_values:
            return
        
        high_avg = sum(high_values) / len(high_values)
        low_avg = sum(low_values) / len(low_values)
        difference = high_avg - low_avg
        
        print(f"{pattern_name}: ê³ ìˆ˜??{high_avg:.2f} vs ?¼ë°˜ {low_avg:.2f} (ì°¨ì´: {difference:+.2f})")
    
    print(f"\n?” ê¸°ìˆ ??ì§€???¨í„´ ë¹„êµ:")
    print("-" * 80)
    
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "RSI ?‰ê· ê°?, "rsi")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜", "bb_position")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "MACD ê°?, "macd")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "ê±°ë˜??ë¹„ìœ¨", "volume_ratio")
    
    # 4?¨ê³„: ?±ê³µ ?¨í„´ ?„ì¶œ
    print(f"\n?ŒŸ 4?¨ê³„: ê³ ìˆ˜??ì¢…ëª© ?±ê³µ ?¨í„´ ?„ì¶œ")
    print("=" * 120)
    
    if high_profit_signals:
        # ê³ ìˆ˜??ê·¸ë£¹???‰ê· ê°?ê³„ì‚°
        avg_rsi = sum(s['rsi'] for s in high_profit_signals if not pd.isna(s['rsi'])) / len([s for s in high_profit_signals if not pd.isna(s['rsi'])])
        avg_bb_pos = sum(s['bb_position'] for s in high_profit_signals if not pd.isna(s['bb_position'])) / len([s for s in high_profit_signals if not pd.isna(s['bb_position'])])
        avg_volume_ratio = sum(s['volume_ratio'] for s in high_profit_signals if not pd.isna(s['volume_ratio'])) / len([s for s in high_profit_signals if not pd.isna(s['volume_ratio'])])
        
        print(f"?¯ ê³ ìˆ˜??ì¢…ëª© ?µì‹¬ ?¨í„´:")
        print(f"   ?“Š RSI: {avg_rsi:.1f} (ì¤‘ë¦½ê¶?? ì?)")
        print(f"   ?“ˆ ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜: {avg_bb_pos:.2f} (0.5 = ì¤‘ì•™??")
        print(f"   ?“Š ê±°ë˜??ë¹„ìœ¨: {avg_volume_ratio:.1f}ë°?(?‰ê·  ?€ë¹?")
        
        # ?¬ì ê°€?´ë“œ?¼ì¸
        print(f"\n?’¡ ?¬ì ê°€?´ë“œ?¼ì¸:")
        print("=" * 100)
        print("?? ?°ì„  ?¬ì ì¡°ê±´ (ê³ ìˆ˜???¨í„´):")
        print(f"   ??RSI {avg_rsi-10:.0f}~{avg_rsi+10:.0f} êµ¬ê°„")
        print(f"   ??ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜ {avg_bb_pos-0.2:.1f}~{avg_bb_pos+0.2:.1f}")
        print(f"   ??ê±°ë˜??{avg_volume_ratio:.1f}ë°??´ìƒ ì¦ê?")
        print("   ??50MA ?°ì¹˜ ???‘ë´‰ ??200MA ?°ì¹˜ ???ìŠ¹ ?¨í„´")
        
        # ?„ì¬ ì¶”ì²œ ì¢…ëª©
        current_recommendations = []
        for signal in high_profit_signals:
            if signal['profit_rate'] > -5:  # ?„ì¬ ?ì‹¤??5% ?´ë‚´??ì¢…ëª©
                current_recommendations.append(signal)
        
        if current_recommendations:
            print(f"\n?ŒŸ ?„ì¬ ì¶”ì²œ ì¢…ëª© ({len(current_recommendations)}ê°?:")
            print("-" * 80)
            for signal in current_recommendations[:5]:  # ?ìœ„ 5ê°œë§Œ ?œì‹œ
                coin_name = signal['coin_name']
                max_profit = signal['max_profit_rate']
                current_profit = signal['profit_rate']
                days_ago = signal['days_ago']
                
                print(f"   ?? {coin_name}: ìµœê³  {max_profit:+.1f}% ?˜ìµ ê¸°ë¡, ?„ì¬ {current_profit:+.1f}% ({days_ago}????? í˜¸)")
    
    return enhanced_results

def analyze_pre_golden_cross_signals():
    """ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰ ? í˜¸ ?ì? (50MA ?°ì¹˜ ???‘ë´‰ ??200MA ?°ì¹˜ ???ìŠ¹ + ê±°ë˜??ì¦ê?)"""
    print(f"\n?¯ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰ ? í˜¸ ?ì? ?œì‘")
    print("?“‹ ?ì? ì¡°ê±´:")
    print("   1. 50MA???¿ê³  ?ˆë˜ ìº”ë“¤")
    print("   2. ?´í›„ ?‘ë´‰ ìº”ë“¤ ì¶œí˜„")
    print("   3. 200MAë¥??°ì¹˜?˜ê³  ê·??„ë¡œ ?¬ë¼ê°?)
    print("   4. ê±°ë˜?‰ì´ ?´ì „ ?€ë¹?ì¦ê?")
    print("   5. ?„ì§ ê³¨ë“ ?¬ë¡œ???´ì „ ?íƒœ (50MA < 200MA)")
    
    # ëª¨ë“  KRW ì¢…ëª© ê°€?¸ì˜¤ê¸?    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("???…ë¹„??ì¢…ëª©??ê°€?¸ì˜¬ ???†ìŠµ?ˆë‹¤.")
        return []
    
    print(f"\n?“Š ì´?{len(all_tickers)}ê°?ì¢…ëª©??? í–‰ ? í˜¸ ë¶„ì„ ì¤?..")
    
    # 1???„ë????„ì¬ê¹Œì? ë¶„ì„
    one_month_ago = datetime.now() - pd.Timedelta(days=30)
    print(f"?“… ë¶„ì„ ê¸°ê°„: {one_month_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    pre_signal_results = []
    
    for i, symbol in enumerate(all_tickers[:20]):  # ì²˜ë¦¬ ?œê°„???„í•´ ?ìœ„ 20ê°œë§Œ ë¶„ì„
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"?” ë¶„ì„ ì¤?.. ({i+1}/20) {coin_name}")
        
        try:
            # 4?œê°„ ?°ì´??ì¡°íšŒ (ì¶©ë¶„???°ì´???•ë³´)
            all_data = []
            limit_per_request = 200
            total_requests = 6  # 1200ê°??°ì´??(??8ê°œì›”ì¹?
            
            for j in range(total_requests):
                try:
                    if j == 0:
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request)
                    else:
                        since = int(all_data[0][0]) - (limit_per_request * 4 * 60 * 60 * 1000)
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request, since=since)
                    
                    if data and len(data) > 0:
                        all_data = data + all_data
                    else:
                        break
                    
                    time.sleep(0.05)
                    
                except Exception as e:
                    break
            
            if not all_data:
                print(f"   ??{coin_name}: ?°ì´??ì¡°íšŒ ?¤íŒ¨")
                continue
            
            # ?°ì´?°í”„?ˆì„ ?ì„± ë°??•ì œ
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 300:
                print(f"   ? ï¸ {coin_name}: ?˜ì§‘???°ì´??ë¶€ì¡?({len(df)}ê°?")
                continue
            
            # ?°ì´???•ì œ
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 300:
                print(f"   ? ï¸ {coin_name}: ?•ì œ ???°ì´??ë¶€ì¡?)
                continue
            
            # ?´ë™?‰ê·  ê³„ì‚° (20MA, 50MA, 200MA)
            df['ma20'] = df['close'].rolling(window=20, center=False).mean()
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200??? íš¨???°ì´?°ë??°ë§Œ ?¬ìš©
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ? ï¸ {coin_name}: MA200 ê³„ì‚° ë¶ˆê?")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 1???´ë‚´ ?°ì´?°ë§Œ ?„í„°ë§?            recent_df = df_valid[df_valid['timestamp'] >= one_month_ago].copy()
            
            if len(recent_df) < 20:
                print(f"   ? ï¸ {coin_name}: 1???´ë‚´ ?°ì´??ë¶€ì¡?)
                continue
            
            # ? í–‰ ? í˜¸ ?ì?
            pre_signals = []
            
            for j in range(10, len(recent_df) - 10):  # ì¶©ë¶„???„í›„ ?°ì´???•ë³´
                curr_row = recent_df.iloc[j]
                
                # ?„ì œ ì¡°ê±´: ?„ì§ ê³¨ë“ ?¬ë¡œ???´ì „ (50MA < 200MA)
                if pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or pd.isna(curr_row['ma20']):
                    continue
                
                if curr_row['ma50'] >= curr_row['ma200']:  # ?´ë? ê³¨ë“ ?¬ë¡œ???íƒœë©??œì™¸
                    continue
                
                # ì¡°ê±´ 1: 50MA ?°ì¹˜ ?•ì¸
                ma50_touch_threshold = curr_row['ma50'] * 0.02  # 2% ?¤ì°¨ ?ˆìš©
                is_ma50_touch = (
                    abs(curr_row['low'] - curr_row['ma50']) <= ma50_touch_threshold or
                    (curr_row['low'] <= curr_row['ma50'] <= curr_row['high'])
                )
                
                if not is_ma50_touch:
                    continue
                
                # ì¡°ê±´ 2: ?´í›„ ?‘ë´‰ ìº”ë“¤ ì¶œí˜„ ?•ì¸
                bullish_found = False
                bullish_index = -1
                
                for k in range(1, min(4, len(recent_df) - j)):
                    next_candle = recent_df.iloc[j + k]
                    if next_candle['close'] > next_candle['open']:  # ?‘ë´‰
                        bullish_found = True
                        bullish_index = j + k
                        break
                
                if not bullish_found:
                    continue
                
                # ì¡°ê±´ 3: 200MA ?°ì¹˜ ???ìŠ¹ ?•ì¸
                ma200_touch_and_rise = False
                ma200_touch_index = -1
                
                for k in range(bullish_index + 1, min(bullish_index + 5, len(recent_df))):
                    check_candle = recent_df.iloc[k]
                    
                    if pd.isna(check_candle['ma200']):
                        continue
                    
                    # 200MA ?°ì¹˜ ?•ì¸
                    ma200_touch_threshold = check_candle['ma200'] * 0.015  # 1.5% ?¤ì°¨ ?ˆìš©
                    is_ma200_touch = (
                        abs(check_candle['low'] - check_candle['ma200']) <= ma200_touch_threshold or
                        (check_candle['low'] <= check_candle['ma200'] <= check_candle['high'])
                    )
                    
                    if is_ma200_touch:
                        # ?°ì¹˜ ???ìŠ¹ ?•ì¸
                        if k + 1 < len(recent_df):
                            next_candle = recent_df.iloc[k + 1]
                            if next_candle['close'] > check_candle['ma200']:
                                ma200_touch_and_rise = True
                                ma200_touch_index = k
                                break
                
                if not ma200_touch_and_rise:
                    continue
                
                # ì¡°ê±´ 4: ê±°ë˜??ì¦ê? ?•ì¸
                volume_surge = False
                if j >= 10:
                    prev_volumes = [recent_df.iloc[j - k]['volume'] for k in range(1, 11)]
                    avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
                    
                    signal_volume = recent_df.iloc[ma200_touch_index]['volume']
                    if signal_volume > avg_prev_volume * 1.3:  # 1.3ë°??´ìƒ
                        volume_surge = True
                
                if not volume_surge:
                    continue
                
                # ? í–‰? í˜¸ ë°œìƒ ?œì  ê¸°ë¡
                signal_date = recent_df.iloc[ma200_touch_index]['timestamp']
                signal_price = recent_df.iloc[ma200_touch_index]['close']
                signal_row = recent_df.iloc[ma200_touch_index]
                
                # ?„ì¬ê°€ ?€ë¹??˜ìµë¥?ê³„ì‚°
                current_price = recent_df.iloc[-1]['close']
                current_profit_rate = ((current_price - signal_price) / signal_price) * 100
                
                pre_signals.append({
                    'coin_name': coin_name,
                    'symbol': symbol,
                    'signal_date': signal_date,
                    'signal_price': signal_price,
                    'current_price': current_price,
                    'current_profit_rate': current_profit_rate,
                    'days_ago': (datetime.now() - signal_date.to_pydatetime()).days
                })
                
                print(f"   ??{coin_name}: ? í–‰? í˜¸ ë°œê²¬ - ?„ì¬ ?˜ìµë¥?{current_profit_rate:.1f}%")
            
            if pre_signals:
                # ê°€??ìµœê·¼ ? í˜¸ë§??€??                latest_signal = pre_signals[-1]
                pre_signal_results.append(latest_signal)
            else:
                print(f"   ??{coin_name}: 1???´ë‚´ ? í–‰? í˜¸ ?†ìŒ")
                
        except Exception as e:
            print(f"   ??{coin_name}: ë¶„ì„ ?¤íŒ¨ - {e}")
            continue
        
        time.sleep(0.05)
    
    if not pre_signal_results:
        print("??? í–‰? í˜¸ë¥?ë°œê²¬??ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        return []
    
    # ê²°ê³¼ ì¶œë ¥
    print(f"\n?“Š ? í–‰? í˜¸ ë¶„ì„ ê²°ê³¼ ({len(pre_signal_results)}ê°?ì¢…ëª©)")
    print("=" * 120)
    
    # ?˜ìµë¥?ê¸°ì??¼ë¡œ ?´ë¦¼ì°¨ìˆœ ?•ë ¬
    pre_signal_results.sort(key=lambda x: x['current_profit_rate'], reverse=True)
    
    print(f"{'?œìœ„':<4} {'ì¢…ëª©':<8} {'? í˜¸??:<12} {'? í˜¸ê°€ê²?:<12} {'?„ì¬ê°€':<12} {'?˜ìµë¥?:<10} {'ê²½ê³¼??:<8}")
    print("-" * 120)
    
    for i, signal in enumerate(pre_signal_results):
        rank = i + 1
        coin_name = signal['coin_name']
        signal_date = signal['signal_date'].strftime('%m-%d')
        signal_price = f"{signal['signal_price']:,.0f}??
        current_price = f"{signal['current_price']:,.0f}??
        profit_rate = f"{signal['current_profit_rate']:+.1f}%"
        days_ago = f"{signal['days_ago']}??
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {signal_price:<12} {current_price:<12} {profit_rate:<10} {days_ago:<8}")
    
    return pre_signal_results

def analyze_recent_pre_signals():
    """3???´ë‚´ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ê¸´ê¸‰ ë¶„ì„"""
    print(f"\n?š¨ 3???´ë‚´ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ê¸´ê¸‰ ë¶„ì„")
    print("?“‹ ëª©ì : ê³¨ë“ ?¬ë¡œ???„ë°• ì¢…ëª© ?¤ì‹œê°?ëª¨ë‹ˆ?°ë§")
    
    # 1ë²?? í–‰? í˜¸ ë¶„ì„ ?¤í–‰
    pre_signals = analyze_pre_golden_cross_signals()
    
    if not pre_signals:
        return []
    
    # 3???´ë‚´ ? í˜¸ë§??„í„°ë§?    three_days_ago = datetime.now() - pd.Timedelta(days=3)
    recent_signals = [s for s in pre_signals if s['signal_date'].to_pydatetime() >= three_days_ago]
    
    if not recent_signals:
        print("??3???´ë‚´ ? í–‰? í˜¸ê°€ ?†ìŠµ?ˆë‹¤.")
        return []
    
    print(f"\n?š¨ 3???´ë‚´ ê¸´ê¸‰ ? í˜¸ ({len(recent_signals)}ê°?")
    print("=" * 100)
    
    for signal in recent_signals:
        print(f"?š¨ {signal['coin_name']}: {signal['days_ago']}????? í˜¸, ?„ì¬ {signal['current_profit_rate']:+.1f}% ?˜ìµ")
    
    return recent_signals

def analyze_high_profit_patterns():
    """ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„"""
    print(f"\n?“Š ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„")
    print("?“‹ ëª©ì : ì°¨íŠ¸ ì§€??ê³µí†µ??ë°œêµ´")
    
    # 1ë²?? í–‰? í˜¸ ë¶„ì„ ?¤í–‰
    pre_signals = analyze_pre_golden_cross_signals()
    
    if not pre_signals:
        return []
    
    # ê³ ìˆ˜??ì¢…ëª© ?„í„°ë§?(?˜ìµë¥?5% ?´ìƒ)
    high_profit_signals = [s for s in pre_signals if s['current_profit_rate'] >= 5]
    
    if not high_profit_signals:
        print("??ê³ ìˆ˜??ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        return []
    
    print(f"\n?“ˆ ê³ ìˆ˜??ì¢…ëª© ({len(high_profit_signals)}ê°?")
    print("=" * 100)
    
    for signal in high_profit_signals:
        print(f"?“ˆ {signal['coin_name']}: {signal['current_profit_rate']:+.1f}% ?˜ìµ")
    
    return high_profit_signals

def analyze_pattern_matching():
    """? í–‰? í˜¸ ??ê³¨ë“ ?¬ë¡œ???„ì²´ ?¨í„´ ?ì„¸ ë¶„ì„"""
    print(f"\n?¯ ? í–‰? í˜¸ ??ê³¨ë“ ?¬ë¡œ???„ì²´ ?¨í„´ ?ì„¸ ë¶„ì„")
    print("?“‹ ë¶„ì„ ëª©ì : ? í–‰? í˜¸ë¶€??ê³¨ë“ ?¬ë¡œ??ë°œìƒê¹Œì????„ì „???¨í„´ ?Œì•…")
    print("?” ?ì„¸ ë¶„ì„ ??ª©:")
    print("   1. ? í–‰? í˜¸ ë°œìƒ ?œì ??ê¸°ìˆ ??ì§€??)
    print("   2. ? í–‰? í˜¸ ??ê³¨ë“ ?¬ë¡œ??ê¸°ê°„ ?™ì•ˆ??ë³€???¨í„´")
    print("   3. ê³¨ë“ ?¬ë¡œ??ë°œìƒ ?œì ???•ì¸ ì§€??)
    print("   4. ?¼ì£¼????ìµœê³  ?˜ìµë¥ ê³¼???ê?ê´€ê³?)
    print("   5. ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?±ê³µ ?¨í„´")
    
    # 1?¨ê³„: ? í–‰? í˜¸ ë¶„ì„ ë°?ê³¨ë“ ?¬ë¡œ??ì¶”ì 
    print("\n?” 1?¨ê³„: ? í–‰? í˜¸ ??ê³¨ë“ ?¬ë¡œ???„ì²´ ?¨í„´ ë¶„ì„ ì¤?..")
    
    # ëª¨ë“  KRW ì¢…ëª© ê°€?¸ì˜¤ê¸?    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("???…ë¹„??ì¢…ëª©??ê°€?¸ì˜¬ ???†ìŠµ?ˆë‹¤.")
        return []
    
    print(f"\n?“Š ì´?{len(all_tickers)}ê°?ì¢…ëª©???„ì²´ ?¨í„´ ë¶„ì„ ì¤?..")
    
    # 2???„ë????„ì¬ê¹Œì? ë¶„ì„ (ê³¨ë“ ?¬ë¡œ?¤ê¹Œì§€ ì¶”ì ?˜ê¸° ?„í•´ ê¸°ê°„ ?•ì¥)
    two_months_ago = datetime.now() - pd.Timedelta(days=60)
    print(f"?“… ë¶„ì„ ê¸°ê°„: {two_months_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    complete_pattern_results = []
    
    for i, symbol in enumerate(all_tickers[:12]):  # ?ì„¸ ë¶„ì„???„í•´ 12ê°œë¡œ ?œí•œ
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"?” ë¶„ì„ ì¤?.. ({i+1}/12) {coin_name}")
        
        try:
            # 4?œê°„ ?°ì´??ì¡°íšŒ (ì¶©ë¶„???°ì´???•ë³´)
            all_data = []
            limit_per_request = 200
            total_requests = 8  # 1600ê°??°ì´??(??10ê°œì›”ì¹?
            
            for j in range(total_requests):
                try:
                    if j == 0:
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request)
                    else:
                        since = int(all_data[0][0]) - (limit_per_request * 4 * 60 * 60 * 1000)
                        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=limit_per_request, since=since)
                    
                    if data and len(data) > 0:
                        all_data = data + all_data
                    else:
                        break
                    
                    time.sleep(0.05)
                    
                except Exception as e:
                    break
            
            if not all_data:
                print(f"   ??{coin_name}: ?°ì´??ì¡°íšŒ ?¤íŒ¨")
                continue
            
            # ?°ì´?°í”„?ˆì„ ?ì„± ë°??•ì œ
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 300:
                print(f"   ? ï¸ {coin_name}: ?˜ì§‘???°ì´??ë¶€ì¡?({len(df)}ê°?")
                continue
            
            # ?°ì´???•ì œ
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 300:
                print(f"   ? ï¸ {coin_name}: ?•ì œ ???°ì´??ë¶€ì¡?)
                continue
            
            # ?´ë™?‰ê·  ê³„ì‚° (20MA, 50MA, 200MA)
            df['ma20'] = df['close'].rolling(window=20, center=False).mean()
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # RSI ê³„ì‚°
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # ë³¼ë¦°?€ ë°´ë“œ ê³„ì‚°
            df['bb_middle'] = df['close'].rolling(window=20).mean()
            bb_std = df['close'].rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
            
            # MACD ê³„ì‚°
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            
            # MA200??? íš¨???°ì´?°ë??°ë§Œ ?¬ìš©
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ? ï¸ {coin_name}: MA200 ê³„ì‚° ë¶ˆê?")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 2???´ë‚´ ?°ì´?°ë§Œ ?„í„°ë§?            recent_df = df_valid[df_valid['timestamp'] >= two_months_ago].copy()
            
            if len(recent_df) < 50:
                print(f"   ? ï¸ {coin_name}: 2???´ë‚´ ?°ì´??ë¶€ì¡?)
                continue
            
            # ? í–‰? í˜¸ ??ê³¨ë“ ?¬ë¡œ???„ì²´ ?¨í„´ ?ì?
            complete_patterns = []
            
            for j in range(20, len(recent_df) - 30):  # ì¶©ë¶„???„í›„ ?°ì´???•ë³´
                curr_row = recent_df.iloc[j]
                
                # ?„ì œ ì¡°ê±´: ?„ì§ ê³¨ë“ ?¬ë¡œ???´ì „ (50MA < 200MA)
                if pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or pd.isna(curr_row['ma20']):
                    continue
                
                if curr_row['ma50'] >= curr_row['ma200']:  # ?´ë? ê³¨ë“ ?¬ë¡œ???íƒœë©??œì™¸
                    continue
                
                # 1?¨ê³„: ? í–‰? í˜¸ ?ì? (50MA ?°ì¹˜ ???‘ë´‰ ??200MA ?°ì¹˜ ???ìŠ¹)
                ma50_touch_threshold = curr_row['ma50'] * 0.02
                is_ma50_touch = (
                    abs(curr_row['low'] - curr_row['ma50']) <= ma50_touch_threshold or
                    (curr_row['low'] <= curr_row['ma50'] <= curr_row['high'])
                )
                
                if not is_ma50_touch:
                    continue
                
                # ?‘ë´‰ ìº”ë“¤ ?•ì¸
                bullish_found = False
                bullish_index = -1
                
                for k in range(1, min(4, len(recent_df) - j)):
                    next_candle = recent_df.iloc[j + k]
                    if next_candle['close'] > next_candle['open']:
                        bullish_found = True
                        bullish_index = j + k
                        break
                
                if not bullish_found:
                    continue
                
                # 200MA ?°ì¹˜ ???ìŠ¹ ?•ì¸
                ma200_touch_and_rise = False
                ma200_touch_index = -1
                
                for k in range(bullish_index + 1, min(bullish_index + 5, len(recent_df))):
                    check_candle = recent_df.iloc[k]
                    
                    if pd.isna(check_candle['ma200']):
                        continue
                    
                    ma200_touch_threshold = check_candle['ma200'] * 0.015
                    is_ma200_touch = (
                        abs(check_candle['low'] - check_candle['ma200']) <= ma200_touch_threshold or
                        (check_candle['low'] <= check_candle['ma200'] <= check_candle['high'])
                    )
                    
                    if is_ma200_touch:
                        if k + 1 < len(recent_df):
                            next_candle = recent_df.iloc[k + 1]
                            if next_candle['close'] > check_candle['ma200']:
                                ma200_touch_and_rise = True
                                ma200_touch_index = k
                                break
                
                if not ma200_touch_and_rise:
                    continue
                
                # ê±°ë˜??ì¦ê? ?•ì¸
                volume_surge = False
                if j >= 10:
                    prev_volumes = [recent_df.iloc[j - k]['volume'] for k in range(1, 11)]
                    avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
                    
                    signal_volume = recent_df.iloc[ma200_touch_index]['volume']
                    if signal_volume > avg_prev_volume * 1.3:
                        volume_surge = True
                
                if not volume_surge:
                    continue
                
                # 2?¨ê³„: ? í–‰? í˜¸ ?´í›„ ê³¨ë“ ?¬ë¡œ??ë°œìƒ ì¶”ì 
                signal_date = recent_df.iloc[ma200_touch_index]['timestamp']
                signal_price = recent_df.iloc[ma200_touch_index]['close']
                signal_index = ma200_touch_index
                
                # ? í–‰? í˜¸ ?´í›„ 30?¼ê°„ ê³¨ë“ ?¬ë¡œ??ë°œìƒ ?¬ë? ?•ì¸
                golden_cross_found = False
                golden_cross_index = -1
                golden_cross_date = None
                golden_cross_price = None
                
                search_end = min(signal_index + 180, len(recent_df))  # 30??= 180ê°?4?œê°„ ìº”ë“¤
                
                for gc_idx in range(signal_index + 1, search_end):
                    if gc_idx >= len(recent_df):
                        break
                        
                    prev_row = recent_df.iloc[gc_idx - 1]
                    curr_gc_row = recent_df.iloc[gc_idx]
                    
                    if (pd.isna(prev_row['ma50']) or pd.isna(prev_row['ma200']) or
                        pd.isna(curr_gc_row['ma50']) or pd.isna(curr_gc_row['ma200'])):
                        continue
                    
                    # ê³¨ë“ ?¬ë¡œ??ì¡°ê±´: ?´ì „?ëŠ” 50MA < 200MA, ?„ì¬??50MA > 200MA
                    if prev_row['ma50'] < prev_row['ma200'] and curr_gc_row['ma50'] > curr_gc_row['ma200']:
                        golden_cross_found = True
                        golden_cross_index = gc_idx
                        golden_cross_date = curr_gc_row['timestamp']
                        golden_cross_price = curr_gc_row['close']
                        break
                
                if not golden_cross_found:
                    continue  # ê³¨ë“ ?¬ë¡œ?¤ê? ë°œìƒ?˜ì? ?Šì? ê²½ìš° ?œì™¸
                
                # 3?¨ê³„: ê³¨ë“ ?¬ë¡œ???´í›„ ?¼ì£¼?¼ê°„ ìµœê³  ?˜ìµë¥?ê³„ì‚°
                one_week_after_gc = golden_cross_date + pd.Timedelta(days=7)
                week_after_gc_data = recent_df[
                    (recent_df['timestamp'] > golden_cross_date) & 
                    (recent_df['timestamp'] <= one_week_after_gc)
                ]
                
                if len(week_after_gc_data) == 0:
                    continue
                
                max_price_after_gc = week_after_gc_data['high'].max()
                max_profit_rate = ((max_price_after_gc - golden_cross_price) / golden_cross_price) * 100
                
                # 4?¨ê³„: ? í–‰? í˜¸ ??ê³¨ë“ ?¬ë¡œ??ê¸°ê°„ ?™ì•ˆ???ì„¸ ?¨í„´ ë¶„ì„
                signal_to_gc_data = recent_df.iloc[signal_index:golden_cross_index+1]
                
                if len(signal_to_gc_data) < 2:
                    continue
                
                # ê¸°ê°„ ?™ì•ˆ???¨í„´ ë¶„ì„
                days_to_golden_cross = (golden_cross_date - signal_date).days
                price_change_to_gc = ((golden_cross_price - signal_price) / signal_price) * 100
                
                # ê¸°ê°„ ?™ì•ˆ???‘ë´‰/?Œë´‰ ë¹„ìœ¨
                bullish_candles_count = sum(1 for _, row in signal_to_gc_data.iterrows() if row['close'] > row['open'])
                total_candles_count = len(signal_to_gc_data)
                bullish_ratio = bullish_candles_count / total_candles_count if total_candles_count > 0 else 0
                
                # ê¸°ê°„ ?™ì•ˆ??ê±°ë˜??ë³€??                signal_volume = recent_df.iloc[signal_index]['volume']
                gc_volume = recent_df.iloc[golden_cross_index]['volume']
                volume_change_ratio = gc_volume / signal_volume if signal_volume > 0 else 1
                
                # ê¸°ê°„ ?™ì•ˆ???‰ê·  ê±°ë˜??                avg_volume_during_period = signal_to_gc_data['volume'].mean()
                volume_surge_ratio = avg_volume_during_period / avg_prev_volume if avg_prev_volume > 0 else 1
                
                # ? í–‰? í˜¸ ?œì ??ê¸°ìˆ ??ì§€??                signal_row = recent_df.iloc[signal_index]
                signal_rsi = signal_row['rsi']
                signal_bb_position = signal_row['bb_position']
                signal_macd = signal_row['macd']
                signal_macd_signal = signal_row['macd_signal']
                signal_ma_gap = abs(signal_row['ma50'] - signal_row['ma200']) / signal_row['ma200'] * 100
                
                # ê³¨ë“ ?¬ë¡œ???œì ??ê¸°ìˆ ??ì§€??                gc_row = recent_df.iloc[golden_cross_index]
                gc_rsi = gc_row['rsi']
                gc_bb_position = gc_row['bb_position']
                gc_macd = gc_row['macd']
                gc_macd_signal = gc_row['macd_signal']
                
                # ê¸°ê°„ ?™ì•ˆ??RSI ë³€??                rsi_change = gc_rsi - signal_rsi if not (pd.isna(signal_rsi) or pd.isna(gc_rsi)) else 0
                
                # ê¸°ê°„ ?™ì•ˆ??ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜ ë³€??                bb_position_change = gc_bb_position - signal_bb_position if not (pd.isna(signal_bb_position) or pd.isna(gc_bb_position)) else 0
                
                # ê¸°ê°„ ?™ì•ˆ??MACD ë³€??                macd_change = gc_macd - signal_macd if not (pd.isna(signal_macd) or pd.isna(gc_macd)) else 0
                
                # ?„ì¬ê°€ ?€ë¹??˜ìµë¥?                current_price = recent_df.iloc[-1]['close']
                current_profit_from_signal = ((current_price - signal_price) / signal_price) * 100
                current_profit_from_gc = ((current_price - golden_cross_price) / golden_cross_price) * 100
                
                complete_patterns.append({
                    'coin_name': coin_name,
                    'symbol': symbol,
                    
                    # ? í–‰? í˜¸ ?•ë³´
                    'signal_date': signal_date,
                    'signal_price': signal_price,
                    'signal_rsi': signal_rsi,
                    'signal_bb_position': signal_bb_position,
                    'signal_macd': signal_macd,
                    'signal_ma_gap': signal_ma_gap,
                    
                    # ê³¨ë“ ?¬ë¡œ???•ë³´
                    'golden_cross_date': golden_cross_date,
                    'golden_cross_price': golden_cross_price,
                    'gc_rsi': gc_rsi,
                    'gc_bb_position': gc_bb_position,
                    'gc_macd': gc_macd,
                    
                    # ? í–‰? í˜¸ ??ê³¨ë“ ?¬ë¡œ??ê¸°ê°„ ?¨í„´
                    'days_to_golden_cross': days_to_golden_cross,
                    'price_change_to_gc': price_change_to_gc,
                    'bullish_ratio_during_period': bullish_ratio,
                    'volume_change_ratio': volume_change_ratio,
                    'volume_surge_ratio': volume_surge_ratio,
                    'rsi_change': rsi_change,
                    'bb_position_change': bb_position_change,
                    'macd_change': macd_change,
                    
                    # ?˜ìµë¥??•ë³´
                    'max_profit_rate_after_gc': max_profit_rate,
                    'current_profit_from_signal': current_profit_from_signal,
                    'current_profit_from_gc': current_profit_from_gc,
                    
                    # ê¸°í? ?•ë³´
                    'total_candles_to_gc': total_candles_count,
                    'max_price_after_gc': max_price_after_gc
                })
                
                print(f"   ??{coin_name}: ?„ì „ ?¨í„´ ë°œê²¬ - ? í˜¸?’GC {days_to_golden_cross}?? GC??ìµœê³  {max_profit_rate:.1f}%")
            
            if complete_patterns:
                complete_pattern_results.extend(complete_patterns)
            else:
                print(f"   ??{coin_name}: ?„ì „ ?¨í„´ ?†ìŒ")
                
        except Exception as e:
            print(f"   ??{coin_name}: ë¶„ì„ ?¤íŒ¨ - {e}")
            continue
        
        time.sleep(0.05)
    
    if not pre_signal_results:
        print("??? í–‰? í˜¸ë¥?ë°œê²¬??ì¢…ëª©???†ìŠµ?ˆë‹¤.")
        return []
    
    # 2?¨ê³„: ?¼ì£¼????ìµœê³  ?˜ìµë¥?ê¸°ì??¼ë¡œ ?•ë ¬
    print(f"\n?“Š 2?¨ê³„: {len(pre_signal_results)}ê°?? í–‰? í˜¸ ì¢…ëª©???¼ì£¼?????˜ìµë¥?ë¶„ì„")
    print("=" * 150)
    
    # ?˜ìµë¥?ê¸°ì??¼ë¡œ ?´ë¦¼ì°¨ìˆœ ?•ë ¬
    pre_signal_results.sort(key=lambda x: x['max_profit_rate'], reverse=True)
    
    # ?ìœ„ ?˜ìµë¥?ì¢…ëª©??ì¶œë ¥
    print(f"{'?œìœ„':<4} {'ì¢…ëª©':<8} {'? í˜¸??:<12} {'? í˜¸ê°€ê²?:<12} {'?¼ì£¼?¼ìµœê³ ê?':<15} {'ìµœê³ ?˜ìµë¥?:<12} {'?„ì¬?˜ìµë¥?:<12}")
    print("-" * 150)
    
    for i, signal in enumerate(pre_signal_results):
        rank = i + 1
        coin_name = signal['coin_name']
        signal_date = signal['signal_date'].strftime('%m-%d')
        signal_price = f"{signal['signal_price']:,.0f}??
        max_price = f"{signal['max_price_in_week']:,.0f}??
        max_profit = f"{signal['max_profit_rate']:+.1f}%"
        current_profit = f"{signal['current_profit_rate']:+.1f}%"
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {signal_price:<12} {max_price:<15} {max_profit:<12} {current_profit:<12}")
    
    # 3?¨ê³„: ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ì¶”ì¶œ
    print(f"\n?¯ 3?¨ê³„: ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ì¶”ì¶œ")
    print("=" * 120)
    
    # ?ìœ„ 30% ì¢…ëª©??ê³ ìˆ˜??ê·¸ë£¹?¼ë¡œ ë¶„ë¥˜
    top_30_percent_count = max(1, len(pre_signal_results) // 3)
    high_profit_signals = pre_signal_results[:top_30_percent_count]
    low_profit_signals = pre_signal_results[top_30_percent_count:]
    
    if len(high_profit_signals) == 0:
        print("??ê³ ìˆ˜??ê·¸ë£¹???†ìŠµ?ˆë‹¤.")
        return pre_signal_results
    
    print(f"?“ˆ ê³ ìˆ˜??ê·¸ë£¹: ?ìœ„ {top_30_percent_count}ê°?ì¢…ëª© (?‰ê·  ?˜ìµë¥? {sum(s['max_profit_rate'] for s in high_profit_signals) / len(high_profit_signals):.1f}%)")
    
    if len(low_profit_signals) > 0:
        print(f"?“‰ ?¼ë°˜ ê·¸ë£¹: ?˜ë¨¸ì§€ {len(low_profit_signals)}ê°?ì¢…ëª© (?‰ê·  ?˜ìµë¥? {sum(s['max_profit_rate'] for s in low_profit_signals) / len(low_profit_signals):.1f}%)")
    
    # ?¨í„´ ë¶„ì„ ?¨ìˆ˜
    def analyze_pattern_differences(high_group, low_group, pattern_name, value_key):
        if not high_group:
            return
        
        # NaN ê°??œê±°
        high_values = [s[value_key] for s in high_group if not pd.isna(s[value_key])]
        
        if not high_values:
            return
        
        high_avg = sum(high_values) / len(high_values)
        
        if low_group:
            low_values = [s[value_key] for s in low_group if not pd.isna(s[value_key])]
            if low_values:
                low_avg = sum(low_values) / len(low_values)
                difference = high_avg - low_avg
                print(f"{pattern_name}: ê³ ìˆ˜??{high_avg:.2f} vs ?¼ë°˜ {low_avg:.2f} (ì°¨ì´: {difference:+.2f})")
            else:
                print(f"{pattern_name}: ê³ ìˆ˜??{high_avg:.2f} (?¼ë°˜ ê·¸ë£¹ ?°ì´???†ìŒ)")
        else:
            print(f"{pattern_name}: ê³ ìˆ˜??{high_avg:.2f} (?¼ë°˜ ê·¸ë£¹ ?†ìŒ)")
    
    print(f"\n?” ê¸°ìˆ ??ì§€???¨í„´ ë¹„êµ:")
    print("-" * 80)
    
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "RSI ?‰ê· ê°?, "rsi")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜", "bb_position")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "MACD ê°?, "macd")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "ê±°ë˜??ë¹„ìœ¨", "volume_ratio")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "MA50-200 ê°„ê²©(%)", "ma50_distance")
    
    # 4?¨ê³„: ?±ê³µ ?¨í„´ ?„ì¶œ
    print(f"\n?ŒŸ 4?¨ê³„: ê³ ìˆ˜??ì¢…ëª© ?±ê³µ ?¨í„´ ?„ì¶œ")
    print("=" * 120)
    
    if high_profit_signals:
        # ê³ ìˆ˜??ê·¸ë£¹???‰ê· ê°?ê³„ì‚°
        rsi_values = [s['rsi'] for s in high_profit_signals if not pd.isna(s['rsi'])]
        bb_values = [s['bb_position'] for s in high_profit_signals if not pd.isna(s['bb_position'])]
        volume_values = [s['volume_ratio'] for s in high_profit_signals if not pd.isna(s['volume_ratio'])]
        ma_values = [s['ma50_distance'] for s in high_profit_signals if not pd.isna(s['ma50_distance'])]
        
        if rsi_values:
            avg_rsi = sum(rsi_values) / len(rsi_values)
        else:
            avg_rsi = 50
            
        if bb_values:
            avg_bb_pos = sum(bb_values) / len(bb_values)
        else:
            avg_bb_pos = 0.5
            
        if volume_values:
            avg_volume_ratio = sum(volume_values) / len(volume_values)
        else:
            avg_volume_ratio = 1.5
            
        if ma_values:
            avg_ma_distance = sum(ma_values) / len(ma_values)
        else:
            avg_ma_distance = 5.0
        
        print(f"?¯ ê³ ìˆ˜??ì¢…ëª© ?µì‹¬ ?¨í„´:")
        print(f"   ?“Š RSI: {avg_rsi:.1f} (ì¤‘ë¦½ê¶?? ì?)")
        print(f"   ?“ˆ ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜: {avg_bb_pos:.2f} (0.5 = ì¤‘ì•™??")
        print(f"   ?“Š ê±°ë˜??ë¹„ìœ¨: {avg_volume_ratio:.1f}ë°?(?‰ê·  ?€ë¹?")
        print(f"   ?“ MA50-200 ê°„ê²©: {avg_ma_distance:.1f}% (ê³¨ë“ ?¬ë¡œ???„ë°•??")
        
        # ?¬ì ê°€?´ë“œ?¼ì¸
        print(f"\n?’¡ ?¬ì ê°€?´ë“œ?¼ì¸:")
        print("=" * 100)
        print("?? ?°ì„  ?¬ì ì¡°ê±´ (ê³ ìˆ˜???¨í„´):")
        print(f"   ??RSI {max(30, avg_rsi-10):.0f}~{min(70, avg_rsi+10):.0f} êµ¬ê°„")
        print(f"   ??ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜ {max(0.1, avg_bb_pos-0.2):.1f}~{min(0.9, avg_bb_pos+0.2):.1f}")
        print(f"   ??ê±°ë˜??{avg_volume_ratio:.1f}ë°??´ìƒ ì¦ê?")
        print(f"   ??MA50-200 ê°„ê²© {avg_ma_distance:.1f}% ?´ë‚´ (ê³¨ë“ ?¬ë¡œ???„ë°•)")
        print("   ??50MA ?°ì¹˜ ???‘ë´‰ ??200MA ?°ì¹˜ ???ìŠ¹ ?¨í„´")
        
        # ?„ì¬ ì¶”ì²œ ì¢…ëª©
        current_recommendations = []
        for signal in high_profit_signals:
            if signal['current_profit_rate'] > -5:  # ?„ì¬ ?ì‹¤??5% ?´ë‚´??ì¢…ëª©
                current_recommendations.append(signal)
        
        if current_recommendations:
            print(f"\n?ŒŸ ?„ì¬ ì¶”ì²œ ì¢…ëª© ({len(current_recommendations)}ê°?:")
            print("-" * 80)
            for signal in current_recommendations[:5]:  # ?ìœ„ 5ê°œë§Œ ?œì‹œ
                coin_name = signal['coin_name']
                max_profit = signal['max_profit_rate']
                current_profit = signal['current_profit_rate']
                days_ago = (datetime.now() - signal['signal_date']).days
                
                print(f"   ?? {coin_name}: ìµœê³  {max_profit:+.1f}% ?˜ìµ ê¸°ë¡, ?„ì¬ {current_profit:+.1f}% ({days_ago}????? í˜¸)")
    
    return pre_signal_results

def basic_test():
    """ê¸°ë³¸ ?ŒìŠ¤??- ?…ë¹„???°ê²° ë°??°ì´??ì¡°íšŒ ?•ì¸"""
    print(f"\n?§ª ?…ë¹„??API ?°ê²° ?ŒìŠ¤???œì‘")
    tickers = get_krw_tickers()[:5]  # ì²˜ìŒ 5ê°œë§Œ ?ŒìŠ¤??    
    for symbol in tickers:
        print(f"\n?” {symbol} ?ŒìŠ¤??ì¤?..")
        
        # ?„ì¬ ê°€ê²?ì¡°íšŒ
        current_price = get_current_price(symbol)
        if current_price:
            print(f"   ?’° ?„ì¬ê°€: {current_price:,.0f} KRW")
        else:
            print(f"   ???„ì¬ê°€ ì¡°íšŒ ?¤íŒ¨")
        
        # OHLCV ?°ì´??ì¡°íšŒ
        df_4h = get_ohlcv(symbol, '4h')
        if df_4h is not None and len(df_4h) > 0:
            latest = df_4h.iloc[-1]
            print(f"   ?“Š ìµœê·¼ ì¢…ê?: {latest['close']:,.0f} KRW")
            print(f"   ?“ˆ ?°ì´??ê°œìˆ˜: {len(df_4h)}ê°?)
            print(f"   ?“… ìµœê·¼ ?…ë°?´íŠ¸: {latest['timestamp'].strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"   ??OHLCV ?°ì´??ì¡°íšŒ ?¤íŒ¨")
        
        time.sleep(0.1)

# ?ŒìŠ¤???¤í–‰
if __name__ == "__main__":
    try:
        print("?¯ ?…ë¹„??ê³¨ë“ ?¬ë¡œ??ì§„ì… ? í˜¸ ë¶„ì„ê¸?)
        print("=" * 60)
        print("?“ˆ ê³¨ë“ ?¬ë¡œ??ë°œìƒ ??3~4ê°œì˜ ?‘ë´‰ ìº”ë“¤??ê°•í•˜ê²??•ì„±?˜ë©´ ì§„ì… ê³ ë ¤")
        print("?“Š ë°˜ë“œ??ê±°ë˜???™ë°˜ ?ìŠ¹???Œë§Œ ?˜ë? ?ˆìŒ")
        print("?? ê³¨ë“ ?¬ë¡œ??+ ?€???ŒíŒŒ + ê±°ë˜??ì¦ê? = ì§„ì§œ ? í˜¸")
        print("? ï¸ ë°˜ë?ë¡?ê±°ë˜???†ì´ ê³¨ë“ ?¬ë¡œ?¤ë§Œ ë°œìƒ ???€ë¶€ë¶??˜ì´??)
        print("=" * 60)
        
        # ? íƒ ë©”ë‰´
        print("\n?“‹ ë¶„ì„ ë©”ë‰´:")
        print("1. ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ë¶„ì„ - 1??ê¸°ì? (50MA?°ì¹˜?’ì–‘ë´‰â†’200MA?°ì¹˜?„ìƒ??ê±°ë˜?‰ì¦ê°€)")
        print("2. ê³¨ë“ ?¬ë¡œ??ë°œìƒ ??ì§„ì…? í˜¸ ë¶„ì„ - 2??ê¸°ì?")
        print("3. ?š¨ 3???´ë‚´ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ê¸´ê¸‰ ë¶„ì„ (ê³¨ë“ ?¬ë¡œ???„ë°• ì¢…ëª©)")
        print("4. ?“Š ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„ (ì°¨íŠ¸ ì§€??ê³µí†µ??ë°œêµ´)")
        print("5. ?¯ ? í–‰? í˜¸ ê¸°ë°˜ ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„ (?¼ì£¼????ìµœê³  ?˜ìµë¥?ì¢…ëª© ?¨í„´ ì¶”ì¶œ)")
        print("6. ?„ì²´ ë¶„ì„ (1ë²?+ 2ë²?")
        
        choice = input("\n? íƒ?˜ì„¸??(1/2/3/4/5/6): ").strip()
        
        if choice == "1":
            # ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ë¶„ì„ (1??ê¸°ì?)
            analyze_pre_golden_cross_signals()
        elif choice == "2":
            # ?…ë¹„????ì¢…ëª©??ê³¨ë“ ?¬ë¡œ??ë¶„ì„ (2??ê¸°ì?)
            analyze_all_coins_golden_cross()
        elif choice == "3":
            # 3???´ë‚´ ê³¨ë“ ?¬ë¡œ???´ì „ ? í–‰? í˜¸ ê¸´ê¸‰ ë¶„ì„
            analyze_recent_pre_signals()
        elif choice == "4":
            # ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„
            analyze_high_profit_patterns()
        elif choice == "5":
            # ? í–‰? í˜¸ ê¸°ë°˜ ê³ ìˆ˜??ì¢…ëª© ?¨í„´ ë¶„ì„
            analyze_pattern_matching()
        elif choice == "6":
            # ?„ì²´ ë¶„ì„
            analyze_pre_golden_cross_signals()
            print("\n" + "="*80)
            analyze_all_coins_golden_cross()
        else:
            print("???˜ëª»??? íƒ?…ë‹ˆ?? ?µì‹¬ ?¨í„´ ë¶€?©ë„ ë¶„ì„???¤í–‰?©ë‹ˆ??")
            analyze_pattern_matching()
        
        print("\n" + "="*80)
        
        # XRP ê³¨ë“ ?¬ë¡œ??ë¶„ì„ (ì£¼ì„ ì²˜ë¦¬)
        # analyze_xrp_golden_cross()
        
        print("\n??ë¶„ì„ ?„ë£Œ!")
        print("\n?’¡ ?¬ì ??ì£¼ì˜?¬í•­:")
        print("   ?¯ ì§„ì… ê³ ë ¤ ? í˜¸ë§??¬ì ê²€??)
        print("   ?“Š ê±°ë˜???†ëŠ” ê³¨ë“ ?¬ë¡œ?¤ëŠ” ë¬´ì‹œ")
        print("   ?? ?€??„  ?ŒíŒŒ + ?‘ë´‰ ?°ì† ??ê°•ë ¥??? í˜¸")
        print("   ? ï¸ ?¬ì??ë³¸ì¸ ì±…ì„?˜ì— ? ì¤‘??ê²°ì •?˜ì„¸??)
    except KeyboardInterrupt:
        print("\n?¹ï¸ ë¶„ì„ ì¤‘ë‹¨??)
    except Exception as e:
        print(f"\n???¤ë¥˜ ë°œìƒ: {e}")
    
    for i, pattern in enumerate(complete_pattern_results):
        rank = i + 1
        coin_name = pattern['coin_name']
        signal_date = pattern['signal_date'].strftime('%m-%d')
        gc_date = pattern['golden_cross_date'].strftime('%m-%d')
        days_to_gc = f"{pattern['days_to_golden_cross']}??
        max_profit = f"{pattern['max_profit_rate_after_gc']:+.1f}%"
        signal_rsi = f"{pattern['signal_rsi']:.0f}" if not pd.isna(pattern['signal_rsi']) else "N/A"
        gc_rsi = f"{pattern['gc_rsi']:.0f}" if not pd.isna(pattern['gc_rsi']) else "N/A"
        bullish_ratio = f"{pattern['bullish_ratio_during_period']:.1%}"
        volume_surge = f"{pattern['volume_surge_ratio']:.1f}x"
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {gc_date:<12} {days_to_gc:<8} {max_profit:<10} {signal_rsi:<8} {gc_rsi:<8} {bullish_ratio:<8} {volume_surge:<10}")
    
    # 3?¨ê³„: ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ê³µí†µ ?¨í„´ ì¶”ì¶œ
    print(f"\n?¯ 3?¨ê³„: ê³ ìˆ˜??ì¢…ëª©?¤ì˜ ? í–‰? í˜¸?’ê³¨? í¬ë¡œìŠ¤ ê³µí†µ ?¨í„´ ì¶”ì¶œ")
    print("=" * 150)
    
    # ?ìœ„ 40% ì¢…ëª©??ê³ ìˆ˜??ê·¸ë£¹?¼ë¡œ ë¶„ë¥˜
    top_40_percent_count = max(1, len(complete_pattern_results) * 2 // 5)
    high_profit_patterns = complete_pattern_results[:top_40_percent_count]
    low_profit_patterns = complete_pattern_results[top_40_percent_count:]
    
    if len(high_profit_patterns) == 0:
        print("??ê³ ìˆ˜??ê·¸ë£¹???†ìŠµ?ˆë‹¤.")
        return complete_pattern_results
    
    print(f"?“ˆ ê³ ìˆ˜??ê·¸ë£¹: ?ìœ„ {top_40_percent_count}ê°?ì¢…ëª© (?‰ê·  GC???˜ìµë¥? {sum(p['max_profit_rate_after_gc'] for p in high_profit_patterns) / len(high_profit_patterns):.1f}%)")
    
    if len(low_profit_patterns) > 0:
        print(f"?“‰ ?¼ë°˜ ê·¸ë£¹: ?˜ë¨¸ì§€ {len(low_profit_patterns)}ê°?ì¢…ëª© (?‰ê·  GC???˜ìµë¥? {sum(p['max_profit_rate_after_gc'] for p in low_profit_patterns) / len(low_profit_patterns):.1f}%)")
    
    # ?¨í„´ ë¶„ì„ ?¨ìˆ˜
    def analyze_complete_pattern_differences(high_group, low_group, pattern_name, value_key):
        if not high_group:
            return
        
        # NaN ê°??œê±°
        high_values = [p[value_key] for p in high_group if not pd.isna(p[value_key])]
        
        if not high_values:
            return
        
        high_avg = sum(high_values) / len(high_values)
        
        if low_group:
            low_values = [p[value_key] for p in low_group if not pd.isna(p[value_key])]
            if low_values:
                low_avg = sum(low_values) / len(low_values)
                difference = high_avg - low_avg
                print(f"{pattern_name}: ê³ ìˆ˜??{high_avg:.2f} vs ?¼ë°˜ {low_avg:.2f} (ì°¨ì´: {difference:+.2f})")
            else:
                print(f"{pattern_name}: ê³ ìˆ˜??{high_avg:.2f} (?¼ë°˜ ê·¸ë£¹ ?°ì´???†ìŒ)")
        else:
            print(f"{pattern_name}: ê³ ìˆ˜??{high_avg:.2f} (?¼ë°˜ ê·¸ë£¹ ?†ìŒ)")
    
    print(f"\n?” ? í–‰? í˜¸ ?œì  ê¸°ìˆ ??ì§€???¨í„´ ë¹„êµ:")
    print("-" * 100)
    
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "? í–‰? í˜¸ RSI", "signal_rsi")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "? í–‰? í˜¸ ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜", "signal_bb_position")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "? í–‰? í˜¸ MACD", "signal_macd")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "? í–‰? í˜¸ MAê°„ê²©(%)", "signal_ma_gap")
    
    print(f"\n?” ê³¨ë“ ?¬ë¡œ???œì  ê¸°ìˆ ??ì§€???¨í„´ ë¹„êµ:")
    print("-" * 100)
    
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "ê³¨ë“ ?¬ë¡œ??RSI", "gc_rsi")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "ê³¨ë“ ?¬ë¡œ??ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜", "gc_bb_position")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "ê³¨ë“ ?¬ë¡œ??MACD", "gc_macd")
    
    print(f"\n?” ? í–‰? í˜¸?’ê³¨? í¬ë¡œìŠ¤ ê¸°ê°„ ?¨í„´ ë¹„êµ:")
    print("-" * 100)
    
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "? í˜¸?’GC ?Œìš”?¼ìˆ˜", "days_to_golden_cross")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "? í˜¸?’GC ê°€ê²©ë???%)", "price_change_to_gc")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "ê¸°ê°„ ì¤??‘ë´‰ë¹„ìœ¨", "bullish_ratio_during_period")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "ê¸°ê°„ ì¤?ê±°ë˜??ì¦ê???, "volume_surge_ratio")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "RSI ë³€?”ëŸ‰", "rsi_change")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜ ë³€??, "bb_position_change")
    analyze_complete_pattern_differences(high_profit_patterns, low_profit_patterns, "MACD ë³€?”ëŸ‰", "macd_change")
    
    # 4?¨ê³„: ?±ê³µ ?¨í„´ ?„ì¶œ
    print(f"\n?ŒŸ 4?¨ê³„: ê³ ìˆ˜??ì¢…ëª© ?„ì „ ?±ê³µ ?¨í„´ ?„ì¶œ")
    print("=" * 150)
    
    if high_profit_patterns:
        # ê³ ìˆ˜??ê·¸ë£¹???‰ê· ê°?ê³„ì‚°
        def safe_avg(values):
            clean_values = [v for v in values if not pd.isna(v)]
            return sum(clean_values) / len(clean_values) if clean_values else 0
        
        avg_signal_rsi = safe_avg([p['signal_rsi'] for p in high_profit_patterns])
        avg_signal_bb = safe_avg([p['signal_bb_position'] for p in high_profit_patterns])
        avg_signal_ma_gap = safe_avg([p['signal_ma_gap'] for p in high_profit_patterns])
        
        avg_gc_rsi = safe_avg([p['gc_rsi'] for p in high_profit_patterns])
        avg_gc_bb = safe_avg([p['gc_bb_position'] for p in high_profit_patterns])
        
        avg_days_to_gc = safe_avg([p['days_to_golden_cross'] for p in high_profit_patterns])
        avg_price_change_to_gc = safe_avg([p['price_change_to_gc'] for p in high_profit_patterns])
        avg_bullish_ratio = safe_avg([p['bullish_ratio_during_period'] for p in high_profit_patterns])
        avg_volume_surge = safe_avg([p['volume_surge_ratio'] for p in high_profit_patterns])
        avg_rsi_change = safe_avg([p['rsi_change'] for p in high_profit_patterns])
        
        print(f"?¯ ê³ ìˆ˜??ì¢…ëª© ?„ì „ ?±ê³µ ?¨í„´:")
        print(f"\n?“Š ? í–‰? í˜¸ ?œì  ìµœì  ì¡°ê±´:")
        print(f"   ??RSI: {avg_signal_rsi:.1f} (ì¤‘ë¦½ê¶?")
        print(f"   ??ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜: {avg_signal_bb:.2f} (0.5 = ì¤‘ì•™??")
        print(f"   ??MA50-200 ê°„ê²©: {avg_signal_ma_gap:.1f}% (ê³¨ë“ ?¬ë¡œ???„ë°•??")
        
        print(f"\n?“ˆ ê³¨ë“ ?¬ë¡œ???œì  ?•ì¸ ì§€??")
        print(f"   ??RSI: {avg_gc_rsi:.1f}")
        print(f"   ??ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜: {avg_gc_bb:.2f}")
        
        print(f"\n??? í–‰? í˜¸?’ê³¨? í¬ë¡œìŠ¤ ê¸°ê°„ ?¨í„´:")
        print(f"   ???‰ê·  ?Œìš”?¼ìˆ˜: {avg_days_to_gc:.1f}??)
        print(f"   ??ê¸°ê°„ ì¤?ê°€ê²©ìƒ?? {avg_price_change_to_gc:.1f}%")
        print(f"   ???‘ë´‰ ìº”ë“¤ ë¹„ìœ¨: {avg_bullish_ratio:.1%}")
        print(f"   ??ê±°ë˜??ì¦ê??? {avg_volume_surge:.1f}ë°?)
        print(f"   ??RSI ?ìŠ¹?? {avg_rsi_change:.1f}")
        
        # ?¬ì ê°€?´ë“œ?¼ì¸
        print(f"\n?’¡ ?„ì „ ?¨í„´ ê¸°ë°˜ ?¬ì ê°€?´ë“œ?¼ì¸:")
        print("=" * 120)
        print("?? 1?¨ê³„ - ? í–‰? í˜¸ ?¬ì°© ì¡°ê±´:")
        print(f"   ??RSI {max(30, avg_signal_rsi-10):.0f}~{min(70, avg_signal_rsi+10):.0f} êµ¬ê°„")
        print(f"   ??ë³¼ë¦°?€ë°´ë“œ ?„ì¹˜ {max(0.1, avg_signal_bb-0.2):.1f}~{min(0.9, avg_signal_bb+0.2):.1f}")
        print(f"   ??MA50-200 ê°„ê²© {avg_signal_ma_gap:.1f}% ?´ë‚´")
        print("   ??50MA ?°ì¹˜ ???‘ë´‰ ??200MA ?°ì¹˜ ???ìŠ¹ + ê±°ë˜??1.3ë°??´ìƒ")
        
        print(f"\n?“ˆ 2?¨ê³„ - ê³¨ë“ ?¬ë¡œ???€ê¸?ë°??•ì¸:")
        print(f"   ??? í–‰? í˜¸ ???‰ê·  {avg_days_to_gc:.0f}????ê³¨ë“ ?¬ë¡œ??ë°œìƒ ?ˆìƒ")
        print(f"   ??ê¸°ê°„ ì¤??‘ë´‰ ë¹„ìœ¨ {avg_bullish_ratio:.0%} ?´ìƒ ? ì?")
        print(f"   ??ê±°ë˜??ì§€?ì  ì¦ê? ({avg_volume_surge:.1f}ë°??˜ì?)")
        print(f"   ??RSI ?ì§„???ìŠ¹ (?‰ê·  {avg_rsi_change:.0f}?¬ì¸??")
        
        print(f"\n?¯ 3?¨ê³„ - ê³¨ë“ ?¬ë¡œ??ë°œìƒ ??ì§„ì…:")
        print(f"   ??ê³¨ë“ ?¬ë¡œ???•ì¸ ??ì¦‰ì‹œ ì§„ì… ê³ ë ¤")
        print(f"   ??ê³¨ë“ ?¬ë¡œ?????¼ì£¼?????‰ê·  {sum(p['max_profit_rate_after_gc'] for p in high_profit_patterns) / len(high_profit_patterns):.1f}% ?˜ìµ ê¸°ë?")
        print(f"   ??RSI {avg_gc_rsi:.0f} ?˜ì??ì„œ ê³¨ë“ ?¬ë¡œ??ë°œìƒ ??ìµœì ")
        
        # ?„ì¬ ì¶”ì²œ ì¢…ëª©
        current_recommendations = []
        for pattern in high_profit_patterns:
            if pattern['current_profit_from_gc'] > -10:  # ê³¨ë“ ?¬ë¡œ???€ë¹??ì‹¤??10% ?´ë‚´??ì¢…ëª©
                current_recommendations.append(pattern)
        
        if current_recommendations:
            print(f"\n?ŒŸ ?„ì¬ ì¶”ì²œ ì¢…ëª© ({len(current_recommendations)}ê°?:")
            print("-" * 120)
            for pattern in current_recommendations[:5]:  # ?ìœ„ 5ê°œë§Œ ?œì‹œ
                coin_name = pattern['coin_name']
                max_profit = pattern['max_profit_rate_after_gc']
                current_profit = pattern['current_profit_from_gc']
                days_ago = (datetime.now() - pattern['golden_cross_date']).days
                signal_days_ago = (datetime.now() - pattern['signal_date']).days
                
                print(f"   ?? {coin_name}: GC??ìµœê³  {max_profit:+.1f}% ê¸°ë¡, ?„ì¬ GC?€ë¹?{current_profit:+.1f}%")
                print(f"      ?“… ? í–‰? í˜¸: {signal_days_ago}??????ê³¨ë“ ?¬ë¡œ?? {days_ago}????)
    
    return complete_pattern_results
