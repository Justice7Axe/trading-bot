
import ccxt
import pandas as pd
import requests
import time
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

# Telegram 설정
# TELEGRAM_TOKEN = '여기에_텔레그램_봇_토큰_입력'
# TELEGRAM_CHAT_ID = '여기에_채팅_ID_입력'

# def send_telegram_message(message: str):
#     url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
#     data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
#     requests.post(url, data=data)

# 업비트 API 초기화
upbit = ccxt.upbit()

def get_krw_tickers():
    try:
        print("📡 업비트 마켓 정보 로딩 중...")
        markets = upbit.load_markets()
        
        # 디버깅: 처음 5개 심볼 확인
        all_symbols = list(markets.keys())
        print(f"🔍 전체 심볼 개수: {len(all_symbols)}")
        print(f"🔍 처음 5개 심볼: {all_symbols[:5]}")
        
        # KRW로 시작하는 심볼 찾기 (다양한 패턴 시도)
        krw_patterns = ['KRW/', 'KRW-', '/KRW']
        krw_tickers = []
        
        for pattern in krw_patterns:
            if pattern == '/KRW':
                found = [symbol for symbol in markets if symbol.endswith(pattern)]
            else:
                found = [symbol for symbol in markets if symbol.startswith(pattern)]
            
            if found:
                print(f"✅ '{pattern}' 패턴으로 {len(found)}개 발견")
                krw_tickers = found
                break
        
        if not krw_tickers:
            print("⚠️ KRW 마켓을 찾을 수 없어 BTC 마켓으로 테스트")
            krw_tickers = [symbol for symbol in markets if 'BTC' in symbol][:5]
        
        return krw_tickers
    except Exception as e:
        print(f"❌ 마켓 정보 로딩 실패: {e}")
        return []

def get_ohlcv(symbol):
    try:
        data = upbit.fetch_ohlcv(symbol, timeframe='4h', limit=300)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"{symbol} OHLCV 가져오기 실패: {e}")
        return None

def check_buy_signal(df):
    df['ma50'] = df['close'].rolling(window=50).mean()
    df['ma200'] = df['close'].rolling(window=200).mean()

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # 골든크로스 전 상태 + MA50이 MA200에 근접 + 가격 반등
    condition = (
        prev['ma50'] < prev['ma200'] and
        (prev['ma200'] - prev['ma50']) / prev['ma200'] < 0.05 and  # 5% 이내 근접
        latest['close'] > latest['ma50'] and
        latest['close'] > prev['close']  # 반등
    )

    return condition

def monitor():
    print(f"\n🔍 모니터링 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 스캔 대상: KRW 마켓 전체 코인")
    tickers = get_krw_tickers()
    print(f"📈 총 {len(tickers)}개 코인 분석 중...")

    signal_count = 0
    # 테스트를 위해 처음 10개만 분석
    test_tickers = tickers[:10]
    print(f"🧪 테스트 모드: 처음 {len(test_tickers)}개 코인만 분석")
    
    for i, symbol in enumerate(test_tickers):
        print(f"📊 분석 중... ({i+1}/{len(test_tickers)}) {symbol}")
        
        df = get_ohlcv(symbol)
        if df is None or len(df) < 200:
            continue
        
        # API 요청 제한 방지를 위한 딜레이
        time.sleep(0.1)

        if check_buy_signal(df):
            current_price = df.iloc[-1]['close']
            ma50 = df.iloc[-1]['ma50']
            ma200 = df.iloc[-1]['ma200']
            
            print("=" * 50)
            print(f"🚀 [매수 신호 포착] {symbol}")
            print(f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"💰 현재가: {current_price:,.0f} KRW")
            print(f"📈 MA50: {ma50:,.0f} KRW")
            print(f"📊 MA200: {ma200:,.0f} KRW")
            print(f"📍 MA50/MA200 비율: {(ma50/ma200)*100:.2f}%")
            print("=" * 50)
            signal_count += 1
            # send_telegram_message(message)
    
    print(f"\n📋 분석 완료: 총 {signal_count}개 매수 신호 발견")

# 테스트 실행
if __name__ == "__main__":
    try:
        monitor()
        print("\n✅ 모니터링 완료!")
    except KeyboardInterrupt:
        print("\n⏹️ 모니터링 중단됨")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")

# 주기적 실행을 원할 경우 아래 주석 해제
scheduler = BlockingScheduler()
scheduler.add_job(monitor, 'interval', minutes=10)
scheduler.start()
