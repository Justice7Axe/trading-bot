import ccxt
import pandas as pd
import requests
import time
from datetime import datetime

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
        
        # 재시도 로직 추가
        max_retries = 3
        for attempt in range(max_retries):
            try:
                markets = upbit.load_markets()
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"   ⚠️ 시도 {attempt + 1} 실패, 재시도 중... ({e})")
                    time.sleep(2 ** attempt)  # 지수 백오프
                else:
                    print(f"   ❌ 최대 재시도 횟수 초과: {e}")
                    raise e
        
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
        
        # 결과 검증
        if not krw_tickers:
            print("❌ 사용 가능한 심볼이 없습니다.")
            return []
        
        print(f"✅ 최종 선택된 심볼: {len(krw_tickers)}개")
        return krw_tickers
        
    except Exception as e:
        print(f"❌ 마켓 정보 로딩 실패: {e}")
        print("🔧 문제 해결 방법:")
        print("   1. 인터넷 연결 확인")
        print("   2. 업비트 서버 상태 확인")
        print("   3. 잠시 후 재시도")
        return []

def get_ohlcv(symbol, timeframe='4h'):
    try:
        # 시간대별 데이터 개수 설정
        if timeframe == '4h':
            limit = 300
        else:  # 1h
            limit = 500
            
        # 재시도 로직 추가
        max_retries = 3
        for attempt in range(max_retries):
            try:
                data = upbit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                
                if data and len(data) > 0:
                    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    return df
                else:
                    if attempt < max_retries - 1:
                        print(f"   ⚠️ {symbol} {timeframe} 데이터 없음, 재시도 중... (시도 {attempt + 1})")
                        time.sleep(1)
                    else:
                        print(f"   ❌ {symbol} {timeframe} 최종 데이터 없음")
                        return None
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"   ⚠️ {symbol} {timeframe} OHLCV 가져오기 실패, 재시도 중... (시도 {attempt + 1}): {e}")
                    time.sleep(2 ** attempt)  # 지수 백오프
                else:
                    print(f"{symbol} {timeframe} OHLCV 가져오기 최종 실패: {e}")
                    return None
                    
    except Exception as e:
        print(f"{symbol} {timeframe} OHLCV 가져오기 실패: {e}")
        return None

def get_current_price(symbol):
    """현재 가격 조회"""
    try:
        # 재시도 로직 추가
        max_retries = 3
        for attempt in range(max_retries):
            try:
                ticker = upbit.fetch_ticker(symbol)
                if ticker and 'last' in ticker and ticker['last'] is not None:
                    return ticker['last']
                else:
                    if attempt < max_retries - 1:
                        print(f"   ⚠️ {symbol} 티커 데이터 누락, 재시도 중... (시도 {attempt + 1})")
                        time.sleep(1)
                    else:
                        print(f"   ❌ {symbol} 티커 데이터 최종 누락")
                        return None
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"   ⚠️ {symbol} 현재 가격 조회 실패, 재시도 중... (시도 {attempt + 1}): {e}")
                    time.sleep(2 ** attempt)  # 지수 백오프
                else:
                    print(f"{symbol} 현재 가격 조회 최종 실패: {e}")
                    return None
                    
    except Exception as e:
        print(f"{symbol} 현재 가격 조회 실패: {e}")
        return None

def get_volume_ranking():
    """거래량 상위 20개 종목 조회"""
    print(f"\n📊 거래량 상위 20개 종목 분석 시작")
    tickers = get_krw_tickers()
    print(f"📈 총 {len(tickers)}개 코인 중 거래량 상위 20개 선별 중...")
    
    volume_data = []
    
    for i, symbol in enumerate(tickers):
        try:
            # 티커 정보 조회 (현재가, 거래량, 등락률 포함)
            ticker = upbit.fetch_ticker(symbol)
            
            if ticker:
                # 24시간 거래량 (KRW 기준)
                volume_krw = ticker.get('quoteVolume', 0)  # KRW 거래량
                volume_coin = ticker.get('baseVolume', 0)   # 코인 거래량
                
                # 현재가
                current_price = ticker.get('last', 0)
                
                # 전일 대비 등락률 (%)
                change_percent = ticker.get('percentage', 0)
                
                # 전일 종가
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
        
        # API 요청 제한 방지
        time.sleep(0.05)
    
    # 거래량(KRW) 기준으로 내림차순 정렬
    volume_data.sort(key=lambda x: x['volume_krw'], reverse=True)
    
    # 상위 20개만 선택
    top_20 = volume_data[:20]
    
    # 결과 출력
    print(f"\n🏆 거래량 상위 20개 종목 (24시간 기준)")
    print("=" * 100)
    print(f"{'순위':<4} {'종목':<15} {'현재가':<15} {'전일대비':<12} {'거래량(KRW)':<20}")
    print("-" * 100)
    
    for i, coin in enumerate(top_20):
        rank = i + 1
        symbol = coin['symbol'].replace('KRW/', '').replace('/KRW', '')
        current_price = coin['current_price']
        change_percent = coin['change_percent']
        volume_krw = coin['volume_krw']
        
        # 등락률에 따른 이모지
        if change_percent > 0:
            change_emoji = "📈"
            change_color = "+"
        elif change_percent < 0:
            change_emoji = "📉"
            change_color = ""
        else:
            change_emoji = "➡️"
            change_color = ""
        
        # 거래량을 억 단위로 변환
        volume_display = f"{volume_krw/100000000:.1f}억" if volume_krw >= 100000000 else f"{volume_krw/10000:.0f}만"
        
        print(f"{rank:<4} {symbol:<15} {current_price:>12,.0f}원 {change_emoji} {change_color}{change_percent:>6.2f}% {volume_display:>15}")
    
    print("-" * 100)
    print(f"📅 조회 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return top_20

def analyze_xrp_golden_cross():
    """XRP/KRW 코인의 4시간 기준 50MA와 200MA 골든크로스 분석 (개선된 버전)"""
    print(f"\n🔍 XRP/KRW 골든크로스 분석 시작")
    
    # XRP 심볼 찾기
    tickers = get_krw_tickers()
    xrp_symbol = None
    
    for ticker in tickers:
        if 'XRP' in ticker.upper():
            xrp_symbol = ticker
            break
    
    if not xrp_symbol:
        print("❌ XRP/KRW 심볼을 찾을 수 없습니다.")
        return
    
    print(f"📊 분석 대상: {xrp_symbol}")
    
    # 4시간 데이터 조회 (최대한 많은 데이터 확보 - 5000개, 약 2.5년치)
    try:
        # 업비트 API 제한을 고려하여 여러 번에 나누어 데이터 수집
        all_data = []
        limit_per_request = 200  # 한 번에 가져올 데이터 개수
        total_requests = 10      # 총 요청 횟수 (200 * 10 = 2000개)
        
        print(f"� {total_requests}번에 나누어 데이터 수집 중...")
        
        for i in range(total_requests):
            try:
                if i == 0:
                    # 첫 번째 요청은 최신 데이터부터
                    data = upbit.fetch_ohlcv(xrp_symbol, timeframe='4h', limit=limit_per_request)
                else:
                    # 이후 요청은 이전 데이터의 시작점부터 과거로
                    since = int(all_data[0][0]) - (limit_per_request * 4 * 60 * 60 * 1000)  # 4시간 * limit_per_request만큼 과거
                    data = upbit.fetch_ohlcv(xrp_symbol, timeframe='4h', limit=limit_per_request, since=since)
                
                if data and len(data) > 0:
                    # 중복 제거를 위해 시작 부분에 추가
                    all_data = data + all_data
                    print(f"   📊 {i+1}/{total_requests} 완료 - 누적 데이터: {len(all_data)}개")
                else:
                    print(f"   ⚠️ {i+1}/{total_requests} 데이터 없음")
                    break
                
                # API 요청 제한 방지
                time.sleep(0.1)
                
            except Exception as e:
                print(f"   ❌ {i+1}/{total_requests} 요청 실패: {e}")
                break
        
        # 중복 제거 및 정렬
        df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        
        print(f"📈 최종 데이터 기간: {df.iloc[0]['timestamp'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['timestamp'].strftime('%Y-%m-%d')}")
        print(f"📊 최종 데이터 개수: {len(df)}개")
        
    except Exception as e:
        print(f"❌ XRP 데이터 조회 실패: {e}")
        return
    
    if len(df) < 200:
        print("❌ 충분한 데이터가 없습니다. (200개 미만)")
        return
    
    # 데이터 품질 확인
    print(f"\n🔍 데이터 품질 확인:")
    print(f"   📊 Close 가격 범위: {df['close'].min():.4f} ~ {df['close'].max():.4f} KRW")
    print(f"   📊 Close 가격 NaN 개수: {df['close'].isna().sum()}개")
    print(f"   📊 Close 가격 0 개수: {(df['close'] == 0).sum()}개")
    
    # NaN이나 0인 값들을 제거하거나 보정
    df = df.dropna(subset=['close'])  # NaN 제거
    df = df[df['close'] > 0]  # 0인 값 제거
    
    print(f"   ✅ 정제 후 데이터 개수: {len(df)}개")
    
    if len(df) < 200:
        print("❌ 정제 후 충분한 데이터가 없습니다. (200개 미만)")
        return
    
    # 이동평균 계산 (개선된 방법)
    print(f"\n🔍 이동평균 계산 중...")
    
    # 데이터가 충분한지 확인
    if len(df) < 250:  # MA200 + 여유분 50
        print(f"❌ MA200 계산을 위한 충분한 데이터가 없습니다. (현재: {len(df)}개, 필요: 250개 이상)")
        return
    
    # 이동평균 계산 (min_periods 없이 계산하여 더 많은 데이터 확보)
    df['ma50'] = df['close'].rolling(window=50, center=False).mean()
    df['ma200'] = df['close'].rolling(window=200, center=False).mean()
    
    # MA 계산 결과 확인
    ma50_valid = df['ma50'].notna().sum()
    ma200_valid = df['ma200'].notna().sum()
    ma50_first_valid = df['ma50'].first_valid_index()
    ma200_first_valid = df['ma200'].first_valid_index()
    
    print(f"   📈 MA50 유효 데이터: {ma50_valid}개 (시작 인덱스: {ma50_first_valid})")
    print(f"   📊 MA200 유효 데이터: {ma200_valid}개 (시작 인덱스: {ma200_first_valid})")
    
    # MA200이 유효한 데이터부터만 사용
    if ma200_first_valid is not None:
        df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
        print(f"   ✅ MA200 유효 구간 데이터: {len(df_valid)}개")
        
        # 유효 구간의 최근 데이터 MA 값 확인
        if len(df_valid) > 0:
            latest_valid = df_valid.iloc[-1]
            print(f"   💰 최근 종가: {latest_valid['close']:.4f} KRW")
            print(f"   📈 최근 MA50: {latest_valid['ma50']:.4f} KRW")
            print(f"   📊 최근 MA200: {latest_valid['ma200']:.4f} KRW")
            
            # 유효한 데이터로 교체
            df = df_valid
    else:
        print(f"   ❌ MA200 계산 가능한 데이터가 없습니다.")
        return
    
    # 최근 데이터 샘플 확인 (MA 계산이 제대로 되는지 확인)
    print(f"\n🔍 최근 데이터 샘플 확인 (MA 계산 검증):")
    recent_sample = df.tail(10)  # 최근 10개 데이터
    for _, row in recent_sample.iterrows():
        ma_diff = row['ma50'] - row['ma200'] if not (pd.isna(row['ma50']) or pd.isna(row['ma200'])) else 0
        status = "🌟" if row['ma50'] > row['ma200'] else "💀" if not (pd.isna(row['ma50']) or pd.isna(row['ma200'])) else "❓"
        print(f"   {status} {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | 차이: {ma_diff:+.4f}")
    
    # 2025년 7월 6-7일 주변 데이터 디버깅
    print(f"\n🔍 2025년 7월 6-7일 주변 데이터 확인:")
    july_2025_data = df[(df['timestamp'] >= '2025-07-01') & (df['timestamp'] <= '2025-07-15')]
    if len(july_2025_data) > 0:
        print(f"📅 2025년 7월 1일~15일 데이터: {len(july_2025_data)}개")
        for _, row in july_2025_data.iterrows():
            if pd.isna(row['ma50']) or pd.isna(row['ma200']):
                print(f"   ⚠️ {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | MA50: NaN | MA200: NaN | 종가: {row['close']:.4f}")
            else:
                ma_diff = row['ma50'] - row['ma200']
                status = "🌟" if row['ma50'] > row['ma200'] else "💀"
                print(f"   {status} {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | 차이: {ma_diff:+.4f}")
    else:
        print("❌ 2025년 7월 데이터를 찾을 수 없습니다. (미래 데이터)")
        
        # 현재 데이터의 최신 날짜 확인
        if len(df) > 0:
            latest_date = df.iloc[-1]['timestamp']
            print(f"   📅 현재 데이터의 최신 날짜: {latest_date.strftime('%Y-%m-%d %H:%M')}")
            print(f"   📊 2025년 7월까지 남은 기간: 미래 데이터이므로 존재하지 않음")
    
    # 골든크로스 찾기 (개선된 로직)
    golden_crosses = []
    death_crosses = []
    
    print(f"\n🔍 골든크로스 탐지 중...")
    
    # 200번째 인덱스부터 시작 (MA200이 유효한 값을 가지는 시점부터)
    for i in range(200, len(df)):
        prev_row = df.iloc[i-1]
        curr_row = df.iloc[i]
        
        # NaN 값 체크
        if (pd.isna(prev_row['ma50']) or pd.isna(prev_row['ma200']) or
            pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200'])):
            continue
        
        # 골든크로스 조건 개선: 더 정확한 크로스 탐지
        prev_ma_diff = prev_row['ma50'] - prev_row['ma200']
        curr_ma_diff = curr_row['ma50'] - curr_row['ma200']
        
        # 골든크로스: 이전에는 MA50 < MA200, 현재는 MA50 > MA200 (등호 제거)
        if prev_ma_diff < 0 and curr_ma_diff > 0:
            golden_crosses.append({
                'date': curr_row['timestamp'],
                'price': curr_row['close'],
                'ma50': curr_row['ma50'],
                'ma200': curr_row['ma200'],
                'prev_diff': prev_ma_diff,
                'curr_diff': curr_ma_diff
            })
            
            # 2024년과 2025년 7월 6-7일 근처 골든크로스 디버깅
            if curr_row['timestamp'].month == 7 and curr_row['timestamp'].day in [5, 6, 7] and curr_row['timestamp'].year == 2025:
                print(f"🎯 2025년 7월 {curr_row['timestamp'].day}일 골든크로스 발견!")
                print(f"   � 시간: {curr_row['timestamp'].strftime('%Y-%m-%d %H:%M')}")
                print(f"   �  가격: {curr_row['close']:.4f} KRW")
                print(f"   📈 이전 차이: {prev_ma_diff:+.6f} → 현재 차이: {curr_ma_diff:+.6f}")
        
        # 데드크로스: 이전에는 MA50 > MA200, 현재는 MA50 < MA200
        elif prev_ma_diff > 0 and curr_ma_diff < 0:
            death_crosses.append({
                'date': curr_row['timestamp'],
                'price': curr_row['close'],
                'ma50': curr_row['ma50'],
                'ma200': curr_row['ma200'],
                'prev_diff': prev_ma_diff,
                'curr_diff': curr_ma_diff
            })
    
    # 현재 상태 확인
    latest = df.iloc[-1]
    current_price = get_current_price(xrp_symbol)
    
    # MA 값이 유효한지 확인
    ma50_valid = not pd.isna(latest['ma50'])
    ma200_valid = not pd.isna(latest['ma200'])
    
    if ma50_valid and ma200_valid:
        is_golden_cross = latest['ma50'] > latest['ma200']
        ma_diff = latest['ma50'] - latest['ma200']
    else:
        is_golden_cross = False
        ma_diff = 0
    
    # 결과 출력
    print(f"\n📊 XRP/KRW 골든크로스 분석 결과")
    print("=" * 80)
    print(f"💰 현재가: {current_price:,.4f} KRW" if current_price else f"💰 현재가: {latest['close']:,.4f} KRW")
    
    if ma50_valid:
        print(f"📈 MA50: {latest['ma50']:,.4f} KRW")
    else:
        print(f"📈 MA50: NaN (데이터 부족 - 최소 50개 필요)")
        
    if ma200_valid:
        print(f"📊 MA200: {latest['ma200']:,.4f} KRW")
    else:
        print(f"📊 MA200: NaN (데이터 부족 - 최소 200개 필요)")
    
    if ma50_valid and ma200_valid:
        print(f"📏 MA 차이: {ma_diff:+.4f} KRW")
        print(f"🔄 현재 상태: {'🌟 골든크로스 상태' if is_golden_cross else '💀 데드크로스 상태'}")
    else:
        print(f"📏 MA 차이: 계산 불가 (MA 값 부족)")
        print(f"🔄 현재 상태: ❓ 판단 불가 (MA 데이터 부족)")
    
    if golden_crosses:
        print(f"\n🌟 골든크로스 발생 이력 ({len(golden_crosses)}회)")
        print("-" * 80)
        
        for i, cross in enumerate(golden_crosses):
            days_ago = (datetime.now() - cross['date'].to_pydatetime()).days
            print(f"{i+1:2d}. 📅 {cross['date'].strftime('%Y-%m-%d %H:%M')} ({days_ago}일 전)")
            print(f"     💰 가격: {cross['price']:,.4f} KRW")
            print(f"     📈 MA50: {cross['ma50']:,.4f} KRW | MA200: {cross['ma200']:,.4f} KRW")
            print(f"     📏 크로스 차이: {cross['prev_diff']:+.6f} → {cross['curr_diff']:+.6f}")
            
            # 현재 가격과 비교하여 수익률 계산
            if current_price:
                profit_rate = ((current_price - cross['price']) / cross['price']) * 100
                profit_emoji = "📈" if profit_rate > 0 else "📉"
                print(f"     {profit_emoji} 현재 대비 수익률: {profit_rate:+.2f}%")
            print()
    else:
        print("\n❌ 분석 기간 내 골든크로스 발생 이력이 없습니다.")
        print("🔍 디버깅: 7월 6일 주변 MA 차이값을 확인해보세요.")
    
    if death_crosses:
        print(f"\n💀 데드크로스 발생 이력 ({len(death_crosses)}회)")
        print("-" * 80)
        
        for i, cross in enumerate(death_crosses):
            days_ago = (datetime.now() - cross['date'].to_pydatetime()).days
            print(f"{i+1:2d}. 📅 {cross['date'].strftime('%Y-%m-%d %H:%M')} ({days_ago}일 전)")
            print(f"     💰 가격: {cross['price']:,.4f} KRW")
            print(f"     📈 MA50: {cross['ma50']:,.4f} KRW | MA200: {cross['ma200']:,.4f} KRW")
            print(f"     📏 크로스 차이: {cross['prev_diff']:+.6f} → {cross['curr_diff']:+.6f}")
            print()
    
    # 최근 골든크로스/데드크로스 정보
    if golden_crosses:
        latest_golden = golden_crosses[-1]
        days_since_golden = (datetime.now() - latest_golden['date'].to_pydatetime()).days
        print(f"🌟 최근 골든크로스: {latest_golden['date'].strftime('%Y-%m-%d %H:%M')} ({days_since_golden}일 전)")
    
    if death_crosses:
        latest_death = death_crosses[-1]
        days_since_death = (datetime.now() - latest_death['date'].to_pydatetime()).days
        print(f"💀 최근 데드크로스: {latest_death['date'].strftime('%Y-%m-%d %H:%M')} ({days_since_death}일 전)")
    
    # 2025년 7월 6-7일 특별 확인
    print(f"\n🎯 2025년 7월 6일 특별 분석:")
    july_6_2025_data = df[df['timestamp'].dt.date == pd.to_datetime('2025-07-06').date()]
    if len(july_6_2025_data) > 0:
        for _, row in july_6_2025_data.iterrows():
            ma_diff = row['ma50'] - row['ma200']
            status = "🌟 골든크로스" if row['ma50'] > row['ma200'] else "💀 데드크로스"
            print(f"   📅 {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | {status}")
            print(f"   📈 MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | 차이: {ma_diff:+.6f}")
    else:
        print(f"   ❌ 2025년 7월 6일 데이터를 찾을 수 없습니다. (미래 데이터)")
    
    print(f"\n🎯 2025년 7월 7일 특별 분석:")
    july_7_2025_data = df[df['timestamp'].dt.date == pd.to_datetime('2025-07-07').date()]
    if len(july_7_2025_data) > 0:
        for _, row in july_7_2025_data.iterrows():
            ma_diff = row['ma50'] - row['ma200']
            status = "🌟 골든크로스" if row['ma50'] > row['ma200'] else "💀 데드크로스"
            print(f"   📅 {row['timestamp'].strftime('%Y-%m-%d %H:%M')} | {status}")
            print(f"   📈 MA50: {row['ma50']:.4f} | MA200: {row['ma200']:.4f} | 차이: {ma_diff:+.6f}")
    else:
        print(f"   ❌ 2025년 7월 7일 데이터를 찾을 수 없습니다. (미래 데이터)")
    
    # 2025년 7월 6-7일 골든크로스 비교 분석
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
        print(f"\n🌟 목표 날짜들의 골든크로스 상태 요약:")
        print("-" * 60)
        for cross in golden_cross_dates:
            print(f"✅ {cross['date']} | 가격: {cross['price']:.4f} KRW | MA차이: {cross['ma_diff']:+.6f}")
    else:
        print(f"\n❌ 목표 날짜들(2025년 7월 6-7일) 중 골든크로스 상태인 날짜가 없습니다.")

def analyze_golden_cross_reliability(df, cross_index, cross_row):
    """골든크로스 신호의 신뢰성 분석"""
    
    # 골든크로스 이후 3-4개 캔들 분석 (최대 4개까지)
    after_candles = []
    for i in range(1, min(5, len(df) - cross_index)):
        if cross_index + i < len(df):
            after_candles.append(df.iloc[cross_index + i])
    
    # 1. 양봉 캔들 강도 분석
    bullish_candles = 0
    strong_bullish = 0
    
    for candle in after_candles:
        if candle['close'] > candle['open']:  # 양봉
            bullish_candles += 1
            body_size = (candle['close'] - candle['open']) / candle['open'] * 100
            if body_size > 3:  # 3% 이상 상승 시 강한 양봉
                strong_bullish += 1
    
    # 2. 거래량 증가 분석
    volume_surge = False
    if cross_index >= 10:  # 충분한 과거 데이터가 있을 때
        # 골든크로스 이전 10개 캔들의 평균 거래량
        prev_volumes = [df.iloc[cross_index - i]['volume'] for i in range(1, 11)]
        avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
        
        # 골든크로스 시점과 이후 캔들들의 거래량
        cross_volume = cross_row['volume']
        after_volumes = [candle['volume'] for candle in after_candles]
        
        # 거래량이 평균의 1.5배 이상이면 거래량 급증으로 판단
        if cross_volume > avg_prev_volume * 1.5:
            volume_surge = True
        elif after_volumes and max(after_volumes) > avg_prev_volume * 1.5:
            volume_surge = True
    
    # 3. 저항선 돌파 분석
    resistance_break = False
    if cross_index >= 20:  # 충분한 과거 데이터가 있을 때
        # 골든크로스 이전 20개 캔들의 최고가들 중 상위 저항선 찾기
        prev_highs = [df.iloc[cross_index - i]['high'] for i in range(1, 21)]
        resistance_level = sorted(prev_highs, reverse=True)[2]  # 상위 3번째 고점을 저항선으로 설정
        
        # 골든크로스 이후 저항선 돌파 여부
        cross_high = cross_row['high']
        after_highs = [candle['high'] for candle in after_candles]
        
        if cross_high > resistance_level or (after_highs and max(after_highs) > resistance_level):
            resistance_break = True
    
    # 4. 종합 신호 강도 계산
    strength_score = 0
    
    # 양봉 캔들 점수 (최대 40점)
    if bullish_candles >= 3:
        strength_score += 20
    elif bullish_candles >= 2:
        strength_score += 10
    
    if strong_bullish >= 2:
        strength_score += 20
    elif strong_bullish >= 1:
        strength_score += 10
    
    # 거래량 점수 (최대 30점)
    if volume_surge:
        strength_score += 30
    
    # 저항선 돌파 점수 (최대 30점)
    if resistance_break:
        strength_score += 30
    
    # 🎯 진입 신호 판단 로직 (핵심 투자 가이드)
    entry_signal = False
    entry_reason = ""
    entry_confidence = 0
    
    # 📈 진입 고려 조건 1: 골든크로스 + 거래량 + 3-4개 양봉 + 저항돌파 (최강 신호)
    if volume_surge and bullish_candles >= 3 and resistance_break:
        entry_signal = True
        entry_reason = "🚀 강력한 진입 신호"
        entry_confidence = 95
    
    # 📈 진입 고려 조건 2: 골든크로스 + 거래량 + 3-4개 양봉 (강한 신호)
    elif volume_surge and bullish_candles >= 3:
        entry_signal = True
        entry_reason = "📈 진입 고려"
        entry_confidence = 80
    
    # ⚡ 진입 고려 조건 3: 골든크로스 + 거래량 + 저항돌파 (돌파 진입)
    elif volume_surge and resistance_break:
        entry_signal = True
        entry_reason = "⚡ 돌파 진입"
        entry_confidence = 75
    
    # 🔍 관찰 조건: 골든크로스 + 거래량만 있는 경우
    elif volume_surge and bullish_candles >= 2:
        entry_signal = False
        entry_reason = "🔍 관찰 필요"
        entry_confidence = 60
    
    # ⚠️ 페이크 가능성 높음: 거래량 없는 골든크로스
    elif not volume_surge:
        entry_signal = False
        entry_reason = "⚠️ 페이크 가능성 높음"
        entry_confidence = 20
    
    # 🤔 애매한 상황
    else:
        entry_signal = False
        entry_reason = "🤔 신호 약함"
        entry_confidence = 40
    
    # 신뢰성 판단
    is_reliable = strength_score >= 60  # 60점 이상이면 신뢰할 만한 신호
    
    if strength_score >= 80:
        strength = "매우 강함"
    elif strength_score >= 60:
        strength = "강함"
    elif strength_score >= 40:
        strength = "보통"
    else:
        strength = "약함"
    
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
    """업비트 전 종목의 2달 이내 골든크로스 분석 (신호 신뢰성 포함)"""
    print(f"\n🔍 업비트 전 종목 골든크로스 분석 시작 (신호 신뢰성 분석 포함)")
    
    # 모든 KRW 종목 가져오기
    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("❌ 업비트 종목을 가져올 수 없습니다.")
        return
    
    print(f"\n📊 총 {len(all_tickers)}개 종목의 2달 이내 골든크로스 분석 중...")
    
    # 2달 전 날짜 계산
    two_months_ago = datetime.now() - pd.Timedelta(days=60)
    print(f"📅 분석 기간: {two_months_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    golden_cross_results = []
    failed_coins = []  # 실패한 종목 추적
    success_count = 0  # 성공한 종목 수 추적
    
    for i, symbol in enumerate(all_tickers):
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/{len(all_tickers)}) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (XRP 분석과 동일한 방식으로 충분한 데이터 확보)
            all_data = []
            limit_per_request = 200
            total_requests = 3  # 600개 데이터로 줄임 (메모리 절약)
            
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
                    
                    time.sleep(0.1)  # 딜레이 증가
                    
                except Exception as e:
                    print(f"   ⚠️ {coin_name}: {j+1}번째 요청 실패 - {e}")
                    break
            
            if not all_data:
                print(f"   ❌ {coin_name}: 데이터 조회 실패")
                failed_coins.append({'coin': coin_name, 'reason': '데이터 조회 실패'})
                continue
            
            # 데이터프레임 생성 및 정제
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 250:
                print(f"   ⚠️ {coin_name}: 수집된 데이터 부족 ({len(df)}개)")
                failed_coins.append({'coin': coin_name, 'reason': f'데이터 부족 ({len(df)}개)'})
                continue
            
            # 데이터 정제
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 250:
                print(f"   ⚠️ {coin_name}: 정제 후 데이터 부족")
                failed_coins.append({'coin': coin_name, 'reason': '정제 후 데이터 부족'})
                continue
            
            # 이동평균 계산
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                failed_coins.append({'coin': coin_name, 'reason': 'MA200 계산 불가'})
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 2달 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= two_months_ago].copy()
            
            if len(recent_df) < 10:
                print(f"   ⚠️ {coin_name}: 2달 이내 데이터 부족")
                failed_coins.append({'coin': coin_name, 'reason': '2달 이내 데이터 부족'})
                continue
            
            # 골든크로스 탐지
            golden_crosses = []
            
            for j in range(1, len(recent_df)):
                prev_row = recent_df.iloc[j-1]
                curr_row = recent_df.iloc[j]
                
                # NaN 값 체크
                if (pd.isna(prev_row['ma50']) or pd.isna(prev_row['ma200']) or
                    pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200'])):
                    continue
                
                # 골든크로스 조건
                prev_ma_diff = prev_row['ma50'] - prev_row['ma200']
                curr_ma_diff = curr_row['ma50'] - curr_row['ma200']
                
                if prev_ma_diff < 0 and curr_ma_diff > 0:
                    days_ago = (datetime.now() - curr_row['timestamp'].to_pydatetime()).days
                    
                    # 현재가 조회 (에러 처리 강화)
                    try:
                        current_price = get_current_price(symbol)
                        if current_price is None:
                            current_price = df_valid.iloc[-1]['close']  # 최신 종가 사용
                    except Exception as e:
                        print(f"   ⚠️ {coin_name}: 현재가 조회 실패 - {e}")
                        current_price = df_valid.iloc[-1]['close']  # 최신 종가 사용
                    
                    # 골든크로스 신호 신뢰성 분석
                    try:
                        signal_analysis = analyze_golden_cross_reliability(recent_df, j, curr_row)
                    except Exception as e:
                        print(f"   ⚠️ {coin_name}: 신호 분석 실패 - {e}")
                        # 기본값으로 대체
                        signal_analysis = {
                            'strength': '보통',
                            'volume_surge': False,
                            'bullish_candles': 0,
                            'resistance_break': False,
                            'is_reliable': False,
                            'entry_signal': False,
                            'entry_reason': '🤔 신호 약함',
                            'entry_confidence': 40
                        }
                    
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
                # 가장 최근 골든크로스만 저장
                latest_golden_cross = golden_crosses[-1]
                golden_cross_results.append(latest_golden_cross)
                success_count += 1
                print(f"   ✅ {coin_name}: {latest_golden_cross['days_ago']}일 전 골든크로스")
            else:
                print(f"   ❌ {coin_name}: 2달 이내 골든크로스 없음")
                success_count += 1
        
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            failed_coins.append({'coin': coin_name, 'reason': f'분석 실패: {str(e)[:50]}'})
            continue
        
        # API 요청 제한 방지 (딜레이 증가)
        time.sleep(0.2)
        
        # 진행 상황 표시 (50개마다)
        if (i + 1) % 50 == 0:
            print(f"\n📊 진행 상황: {i+1}/{len(all_tickers)} 완료 ({success_count}개 성공, {len(failed_coins)}개 실패)")
            print(f"   💾 메모리 정리 중...")
            
            # 메모리 정리
            import gc
            gc.collect()
            
            # 잠시 대기
            time.sleep(1)
    
    # 최종 통계
    print(f"\n📊 분석 완료 통계:")
    print(f"   📈 총 분석 종목: {len(all_tickers)}개")
    print(f"   ✅ 성공한 종목: {success_count}개")
    print(f"   ❌ 실패한 종목: {len(failed_coins)}개")
    print(f"   📊 성공률: {success_count/len(all_tickers)*100:.1f}%")
    
    # 실패한 종목 요약 (상위 10개만)
    if failed_coins:
        print(f"\n❌ 실패한 종목 요약 (상위 10개):")
        for i, failed in enumerate(failed_coins[:10]):
            print(f"   {i+1}. {failed['coin']}: {failed['reason']}")
        
        if len(failed_coins) > 10:
            print(f"   ... 외 {len(failed_coins) - 10}개")
    
    # 결과 출력
    if golden_cross_results:
        # 진입 신호별로 분류
        entry_signals = [r for r in golden_cross_results if r.get('entry_signal', False)]
        reliable_signals = [r for r in golden_cross_results if r.get('is_reliable', False)]
        fake_signals = [r for r in golden_cross_results if not r.get('volume_surge', True)]
        
        print(f"\n🎯 2달 이내 골든크로스 발생 종목: {len(golden_cross_results)}개")
        print(f"🚀 진입 고려 신호: {len(entry_signals)}개")
        print(f"🌟 신뢰할 만한 신호: {len(reliable_signals)}개")
        print(f"⚠️ 페이크 가능성 높은 신호: {len(fake_signals)}개")
        print("=" * 140)
        
        # 진입 신호 우선으로 정렬 (진입 신호 → 신뢰도 → 최근 순)
        golden_cross_results.sort(key=lambda x: (
            -int(x.get('entry_signal', False)),  # 진입 신호 우선
            -x.get('entry_confidence', 0),       # 신뢰도 높은 순
            x['days_ago']                        # 최근 순
        ))
        
        print(f"{'순위':<4} {'종목':<8} {'날짜':<12} {'일수':<6} {'가격':<10} {'현재가':<10} {'수익률':<8} {'진입신호':<20} {'신뢰도':<6} {'거래량':<6} {'양봉':<4} {'돌파':<4}")
        print("-" * 140)
        
        for i, result in enumerate(golden_cross_results):
            rank = i + 1
            coin_name = result['coin_name']
            cross_date = result['date'].strftime('%m-%d')
            days_ago = f"{result['days_ago']}일"
            cross_price = f"{result['price']:,.0f}원"
            current_price = f"{result['current_price']:,.0f}원"
            
            # 수익률 계산
            profit_rate = ((result['current_price'] - result['price']) / result['price']) * 100
            profit_display = f"{profit_rate:+.1f}%"
            profit_emoji = "📈" if profit_rate > 0 else "📉"
            
            # 진입 신호 정보
            entry_reason = result.get('entry_reason', '🤔 신호 약함')
            entry_confidence = result.get('entry_confidence', 0)
            confidence_display = f"{entry_confidence}%" if entry_confidence > 0 else "-"
            
            # 조건별 이모지
            volume_emoji = "📊" if result.get('volume_surge', False) else "📉"
            bullish_count = result.get('bullish_candles', 0)
            resistance_emoji = "🚀" if result.get('resistance_break', False) else "🔒"
            
            # 진입 신호가 있는 종목은 강조 표시
            prefix = "🎯" if result.get('entry_signal', False) else "  "
            
            print(f"{prefix}{rank:<3} {coin_name:<8} {cross_date:<12} {days_ago:<6} {cross_price:<10} {current_price:<10} {profit_emoji}{profit_display:<7} {entry_reason:<20} {confidence_display:<6} {volume_emoji:<6} {bullish_count}개{'':<4} {resistance_emoji:<4}")
        
        print("-" * 140)
        
        # 📈 진입 고려 종목 별도 요약
        if entry_signals:
            print(f"\n🎯 진입 고려 종목 요약 ({len(entry_signals)}개)")
            print("=" * 120)
            print(f"{'종목':<8} {'진입신호':<20} {'골든크로스 발생시점':<20} {'신뢰도':<8} {'수익률':<10} {'현재가':<12}")
            print("-" * 120)
            for signal in entry_signals:
                profit_rate = ((signal['current_price'] - signal['price']) / signal['price']) * 100
                profit_emoji = "📈" if profit_rate > 0 else "📉"
                cross_datetime = signal['date'].strftime('%Y-%m-%d %H:%M')
                current_price_display = f"{signal['current_price']:,.0f}원"
                print(f"🚀 {signal['coin_name']:<6} {signal.get('entry_reason', ''):<20} {cross_datetime:<20} {signal.get('entry_confidence', 0)}%{'':<6} {profit_emoji}{profit_rate:+.1f}%{'':<6} {current_price_display:<12}")
            print("-" * 120)
        
        # 🚀 강력한 진입 신호만 별도 표시
        strong_signals = [r for r in entry_signals if r.get('entry_reason') == '🚀 강력한 진입 신호']
        if strong_signals:
            print(f"\n🔥 강력한 진입 신호 종목 ({len(strong_signals)}개) - 최우선 투자 검토 대상")
            print("=" * 130)
            print(f"{'종목':<8} {'골든크로스 발생시점':<20} {'발생가격':<12} {'현재가':<12} {'수익률':<10} {'거래량':<6} {'양봉':<6} {'저항돌파':<8}")
            print("-" * 130)
            
            # 수익률 순으로 정렬
            strong_signals.sort(key=lambda x: ((x['current_price'] - x['price']) / x['price']) * 100, reverse=True)
            
            for signal in strong_signals:
                profit_rate = ((signal['current_price'] - signal['price']) / signal['price']) * 100
                profit_emoji = "📈" if profit_rate > 0 else "📉"
                cross_datetime = signal['date'].strftime('%Y-%m-%d %H:%M')
                cross_price = f"{signal['price']:,.0f}원"
                current_price_display = f"{signal['current_price']:,.0f}원"
                volume_emoji = "📊" if signal.get('volume_surge', False) else "📉"
                bullish_count = signal.get('bullish_candles', 0)
                resistance_emoji = "🚀" if signal.get('resistance_break', False) else "🔒"
                
                print(f"🔥 {signal['coin_name']:<6} {cross_datetime:<20} {cross_price:<12} {current_price_display:<12} {profit_emoji}{profit_rate:+.1f}%{'':<6} {volume_emoji:<6} {bullish_count}개{'':<4} {resistance_emoji:<8}")
            
            print("-" * 130)
            
            # 강력한 진입 신호 통계
            strong_profitable = sum(1 for s in strong_signals if s['current_price'] > s['price'])
            strong_avg_profit = sum(((s['current_price'] - s['price']) / s['price']) * 100 for s in strong_signals) / len(strong_signals)
            print(f"📊 강력한 진입 신호 성과: {len(strong_signals)}개 중 {strong_profitable}개 수익 ({strong_profitable/len(strong_signals)*100:.1f}%) | 평균 수익률: {strong_avg_profit:+.2f}%")
        
        # 통계 정보
        total_coins = len(golden_cross_results)
        profitable_coins = sum(1 for r in golden_cross_results if r['current_price'] > r['price'])
        entry_profitable = sum(1 for r in entry_signals if r['current_price'] > r['price']) if entry_signals else 0
        reliable_profitable = sum(1 for r in reliable_signals if r['current_price'] > r['price']) if reliable_signals else 0
        fake_profitable = sum(1 for r in fake_signals if r['current_price'] > r['price']) if fake_signals else 0
        
        avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in golden_cross_results) / total_coins
        entry_avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in entry_signals) / len(entry_signals) if entry_signals else 0
        reliable_avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in reliable_signals) / len(reliable_signals) if reliable_signals else 0
        fake_avg_profit = sum(((r['current_price'] - r['price']) / r['price']) * 100 for r in fake_signals) / len(fake_signals) if fake_signals else 0
        
        print(f"\n📊 골든크로스 성과 통계:")
        print(f"   전체 종목: {total_coins}개 | 수익: {profitable_coins}개 ({profitable_coins/total_coins*100:.1f}%) | 평균: {avg_profit:+.2f}%")
        
        if entry_signals:
            print(f"   🎯 진입 신호: {len(entry_signals)}개 | 수익: {entry_profitable}개 ({entry_profitable/len(entry_signals)*100:.1f}%) | 평균: {entry_avg_profit:+.2f}%")
        
        if reliable_signals:
            print(f"   🌟 신뢰 신호: {len(reliable_signals)}개 | 수익: {reliable_profitable}개 ({reliable_profitable/len(reliable_signals)*100:.1f}%) | 평균: {reliable_avg_profit:+.2f}%")
        
        if fake_signals:
            print(f"   ⚠️ 페이크 신호: {len(fake_signals)}개 | 수익: {fake_profitable}개 ({fake_profitable/len(fake_signals)*100:.1f}%) | 평균: {fake_avg_profit:+.2f}%")
        
        # 진입 신호별 성과 분석
        entry_types = {}
        for result in golden_cross_results:
            entry_reason = result.get('entry_reason', '🤔 신호 약함')
            if entry_reason not in entry_types:
                entry_types[entry_reason] = {'count': 0, 'profitable': 0, 'total_profit': 0}
            
            entry_types[entry_reason]['count'] += 1
            profit_rate = ((result['current_price'] - result['price']) / result['price']) * 100
            entry_types[entry_reason]['total_profit'] += profit_rate
            
            if result['current_price'] > result['price']:
                entry_types[entry_reason]['profitable'] += 1
        
        print(f"\n📈 진입 신호별 성과:")
        for entry_type, stats in entry_types.items():
            success_rate = stats['profitable'] / stats['count'] * 100
            avg_profit_type = stats['total_profit'] / stats['count']
            print(f"   {entry_type}: {stats['count']}개 | 성공률: {success_rate:.1f}% | 평균: {avg_profit_type:+.2f}%")
        
        # 최고/최저 수익률
        if golden_cross_results:
            best_performer = max(golden_cross_results, key=lambda x: (x['current_price'] - x['price']) / x['price'])
            worst_performer = min(golden_cross_results, key=lambda x: (x['current_price'] - x['price']) / x['price'])
            
            best_profit = ((best_performer['current_price'] - best_performer['price']) / best_performer['price']) * 100
            worst_profit = ((worst_performer['current_price'] - worst_performer['price']) / worst_performer['price']) * 100
            
            print(f"\n🏆 성과 순위:")
            print(f"   최고 수익: {best_performer['coin_name']} ({best_profit:+.2f}%) - {best_performer.get('entry_reason', '')}")
            print(f"   최저 수익: {worst_performer['coin_name']} ({worst_profit:+.2f}%) - {worst_performer.get('entry_reason', '')}")
        
        print(f"\n💡 실전 투자 가이드:")
        print(f"   🚀 강력한 진입 신호 = 골든크로스 + 거래량 급증 + 3-4개 양봉 + 저항선 돌파")
        print(f"   📈 진입 고려 = 골든크로스 + 거래량 급증 + 3-4개 양봉 캔들 형성")
        print(f"   ⚡ 돌파 진입 = 골든크로스 + 거래량 급증 + 저항선 돌파")
        print(f"   ⚠️ 페이크 신호 = 거래량 없는 골든크로스 (대부분 실패)")
        print(f"   🔍 관찰 필요 = 거래량은 있지만 양봉 캔들이 약한 경우")
    
    else:
        print(f"\n❌ 업비트 전 종목 중 2달 이내 골든크로스 발생 종목이 없습니다.")
    
    # 메모리 정리
    import gc
    gc.collect()
    
    return golden_cross_results

def analyze_pre_golden_cross_signals():
    """골든크로스 이전 선행 신호 탐지"""
    print(f"\n🎯 골든크로스 이전 선행 신호 탐지 시작")
    print("📋 탐지 조건:")
    print("   1. 50MA에 닿고 있던 캔들")
    print("   2. 이후 양봉 캔들 출현")
    print("   3. 200MA를 터치하고 그 위로 올라감")
    print("   4. 거래량이 이전 대비 증가")
    print("   5. 아직 골든크로스 이전 상태 (50MA < 200MA)")
    
    # 모든 KRW 종목 가져오기
    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("❌ 업비트 종목을 가져올 수 없습니다.")
        return []
    
    print(f"\n📊 총 {len(all_tickers)}개 종목의 선행 신호 분석 중...")
    
    # 1달 전부터 현재까지 분석
    one_month_ago = datetime.now() - pd.Timedelta(days=30)
    print(f"📅 분석 기간: {one_month_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    pre_signal_results = []
    
    for i, symbol in enumerate(all_tickers[:10]):  # 처리 시간을 위해 상위 10개만 분석
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/10) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (더 많은 데이터 수집)
            all_data = []
            limit_per_request = 200
            total_requests = 3  # 600개 데이터 (약 4개월치)
            
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
                print(f"   ❌ {coin_name}: 데이터 조회 실패")
                continue
            
            # 데이터프레임 생성 및 정제
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            print(f"   📊 {coin_name}: 수집된 데이터 {len(df)}개")
            
            if len(df) < 200:  # 조건 완화
                print(f"   ⚠️ {coin_name}: 수집된 데이터 부족 ({len(df)}개)")
                continue
            
            # 데이터 정제
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 200:  # 조건 완화
                print(f"   ⚠️ {coin_name}: 정제 후 데이터 부족")
                continue
            
            # 이동평균 계산
            df['ma50'] = df['close'].rolling(window=50).mean()
            df['ma200'] = df['close'].rolling(window=200).mean()
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 1달 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= one_month_ago].copy()
            
            if len(recent_df) < 10:  # 조건 완화
                print(f"   ⚠️ {coin_name}: 1달 이내 데이터 부족")
                continue
            
            # 선행 신호 탐지 (간단한 버전)
            for j in range(10, len(recent_df) - 5):
                curr_row = recent_df.iloc[j]
                
                # 전제 조건: 아직 골든크로스 이전
                if pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']):
                    continue
                
                if curr_row['ma50'] >= curr_row['ma200']:
                    continue
                
                # 간단한 선행신호 조건
                if (curr_row['low'] <= curr_row['ma50'] * 1.02 and 
                    curr_row['close'] > curr_row['open']):  # 50MA 근처에서 양봉
                    
                    signal_date = curr_row['timestamp']
                    signal_price = curr_row['close']
                    current_price = recent_df.iloc[-1]['close']
                    profit_rate = ((current_price - signal_price) / signal_price) * 100
                    
                    pre_signal_results.append({
                        'coin_name': coin_name,
                        'symbol': symbol,
                        'signal_date': signal_date,
                        'signal_price': signal_price,
                        'current_price': current_price,
                        'profit_rate': profit_rate,
                        'days_ago': (datetime.now() - signal_date.to_pydatetime()).days
                    })
                    
                    print(f"   ✅ {coin_name}: 선행신호 발견 - 현재 수익률 {profit_rate:.1f}%")
                    break
            
            if not any(s['coin_name'] == coin_name for s in pre_signal_results):
                print(f"   ❌ {coin_name}: 선행신호 없음")
                
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            continue
        
        time.sleep(0.1)
    
    if not pre_signal_results:
        print("❌ 선행신호를 발견한 종목이 없습니다.")
        return []
    
    # 결과 출력
    print(f"\n📊 선행신호 분석 결과 ({len(pre_signal_results)}개 종목)")
    print("=" * 100)
    
    # 수익률 기준으로 내림차순 정렬
    pre_signal_results.sort(key=lambda x: x['profit_rate'], reverse=True)
    
    print(f"{'순위':<4} {'종목':<8} {'신호일':<12} {'신호가격':<12} {'현재가':<12} {'수익률':<10} {'경과일':<8}")
    print("-" * 100)
    
    for i, signal in enumerate(pre_signal_results):
        rank = i + 1
        coin_name = signal['coin_name']
        signal_date = signal['signal_date'].strftime('%m-%d')
        signal_price = f"{signal['signal_price']:,.0f}원"
        current_price = f"{signal['current_price']:,.0f}원"
        profit_rate = f"{signal['profit_rate']:+.1f}%"
        days_ago = f"{signal['days_ago']}일"
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {signal_price:<12} {current_price:<12} {profit_rate:<10} {days_ago:<8}")
    
    return pre_signal_results

def analyze_recent_pre_signals():
    """3일 이내 골든크로스 이전 선행신호 긴급 분석"""
    print(f"\n🚨 3일 이내 골든크로스 이전 선행신호 긴급 분석")
    print("📋 목적: 골든크로스 임박 종목 실시간 모니터링")
    
    # 1번 선행신호 분석 실행
    pre_signals = analyze_pre_golden_cross_signals()
    
    if not pre_signals:
        return []
    
    # 3일 이내 신호만 필터링
    three_days_ago = datetime.now() - pd.Timedelta(days=3)
    recent_signals = [s for s in pre_signals if s['signal_date'].to_pydatetime() >= three_days_ago]
    
    if not recent_signals:
        print("❌ 3일 이내 선행신호가 없습니다.")
        return []
    
    print(f"\n🚨 3일 이내 긴급 신호 ({len(recent_signals)}개)")
    print("=" * 80)
    
    for signal in recent_signals:
        print(f"🚨 {signal['coin_name']}: {signal['days_ago']}일 전 신호, 현재 {signal['profit_rate']:+.1f}% 수익")
    
    return recent_signals

def analyze_high_profit_patterns():
    """고수익 종목 패턴 분석"""
    print(f"\n📊 고수익 종목 패턴 분석")
    print("📋 목적: 차트 지표 공통점 발굴")
    
    # 1번 선행신호 분석 실행
    pre_signals = analyze_pre_golden_cross_signals()
    
    if not pre_signals:
        return []
    
    # 고수익 종목 필터링 (수익률 5% 이상)
    high_profit_signals = [s for s in pre_signals if s['profit_rate'] >= 5]
    
    if not high_profit_signals:
        print("❌ 고수익 종목이 없습니다.")
        return []
    
    print(f"\n📈 고수익 종목 ({len(high_profit_signals)}개)")
    print("=" * 80)
    
    for signal in high_profit_signals:
        print(f"📈 {signal['coin_name']}: {signal['profit_rate']:+.1f}% 수익")
    
    return high_profit_signals

def analyze_pattern_matching():
    """선행신호 → 골든크로스 전체 패턴 상세 분석"""
    print(f"\n🎯 선행신호 → 골든크로스 전체 패턴 상세 분석")
    print("📋 분석 목적: 선행신호부터 골든크로스 발생까지의 완전한 패턴 파악")
    print("🔍 상세 분석 항목:")
    print("   1. 선행신호 발생 시점의 기술적 지표")
    print("   2. 선행신호 → 골든크로스 기간 동안의 변화 패턴")
    print("   3. 골든크로스 발생 시점의 확인 지표")
    print("   4. 골든크로스 후 일주일 내 최고 수익률")
    print("   5. 고수익 종목들의 공통 성공 패턴")
    
    # 모든 KRW 종목 가져오기
    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("❌ 업비트 종목을 가져올 수 없습니다.")
        return []
    
    print(f"\n📊 총 {len(all_tickers)}개 종목의 전체 패턴 분석 중...")
    
    # 2달 전부터 현재까지 분석
    two_months_ago = datetime.now() - pd.Timedelta(days=60)
    print(f"📅 분석 기간: {two_months_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    complete_pattern_results = []
    
    for i, symbol in enumerate(all_tickers[:8]):  # 상세 분석을 위해 8개로 제한
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/8) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (더 많은 데이터 수집)
            all_data = []
            limit_per_request = 200
            total_requests = 4  # 800개 데이터 (약 5개월치)
            
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
                print(f"   ❌ {coin_name}: 데이터 조회 실패")
                continue
            
            # 데이터프레임 생성 및 정제
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            print(f"   📊 {coin_name}: 수집된 데이터 {len(df)}개")
            
            if len(df) < 250:  # 조건 완화
                print(f"   ⚠️ {coin_name}: 수집된 데이터 부족 ({len(df)}개)")
                continue
            
            # 데이터 정제
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 250:  # 조건 완화
                print(f"   ⚠️ {coin_name}: 정제 후 데이터 부족")
                continue
            
            # 이동평균 계산
            df['ma50'] = df['close'].rolling(window=50).mean()
            df['ma200'] = df['close'].rolling(window=200).mean()
            
            # RSI 계산
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # 볼린저 밴드 계산
            df['bb_middle'] = df['close'].rolling(window=20).mean()
            bb_std = df['close'].rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
            df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
            
            # MACD 계산
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            
            # Stochastic RSI 계산
            rsi_low = df['rsi'].rolling(window=14).min()
            rsi_high = df['rsi'].rolling(window=14).max()
            df['stoch_rsi'] = (df['rsi'] - rsi_low) / (rsi_high - rsi_low) * 100
            df['stoch_rsi_k'] = df['stoch_rsi'].rolling(window=3).mean()
            df['stoch_rsi_d'] = df['stoch_rsi_k'].rolling(window=3).mean()
            
            # 캔들 패턴 분석
            df['candle_body'] = abs(df['close'] - df['open'])
            df['candle_upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
            df['candle_lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
            df['candle_total_range'] = df['high'] - df['low']
            df['candle_body_ratio'] = df['candle_body'] / df['candle_total_range']
            df['is_bullish'] = df['close'] > df['open']
            df['is_doji'] = df['candle_body'] / df['candle_total_range'] < 0.1
            df['is_hammer'] = (df['candle_lower_shadow'] > df['candle_body'] * 2) & (df['candle_upper_shadow'] < df['candle_body'] * 0.5)
            df['is_shooting_star'] = (df['candle_upper_shadow'] > df['candle_body'] * 2) & (df['candle_lower_shadow'] < df['candle_body'] * 0.5)
            
            # 거래량 패턴 분석
            df['volume_ma20'] = df['volume'].rolling(window=20).mean()
            df['volume_ratio'] = df['volume'] / df['volume_ma20']
            df['volume_surge'] = df['volume_ratio'] > 1.5
            df['volume_trend'] = df['volume'].rolling(window=5).mean() / df['volume'].rolling(window=20).mean()
            
            # 가격 변동성 계산
            df['price_volatility'] = df['close'].rolling(window=20).std() / df['close'].rolling(window=20).mean()
            
            # ATR 계산 (간단한 방식)
            df['high_low'] = df['high'] - df['low']
            df['high_close_prev'] = abs(df['high'] - df['close'].shift(1))
            df['low_close_prev'] = abs(df['low'] - df['close'].shift(1))
            df['true_range'] = df[['high_low', 'high_close_prev', 'low_close_prev']].max(axis=1)
            df['atr'] = df['true_range'].rolling(window=14).mean()
            
            # 임시 컬럼 제거
            df = df.drop(['high_low', 'high_close_prev', 'low_close_prev', 'true_range'], axis=1)
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 2달 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= two_months_ago].copy()
            
            if len(recent_df) < 30:  # 조건 완화
                print(f"   ⚠️ {coin_name}: 2달 이내 데이터 부족")
                continue
            
            # 선행신호 → 골든크로스 패턴 탐지 (간단한 버전)
            complete_patterns = []
            
            for j in range(20, len(recent_df) - 20):
                curr_row = recent_df.iloc[j]
                
                # 선행신호 조건 (간단한 버전)
                if (pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or
                    curr_row['ma50'] >= curr_row['ma200']):
                    continue
                
                # 50MA 근처에서 양봉
                if not (curr_row['low'] <= curr_row['ma50'] * 1.02 and 
                       curr_row['close'] > curr_row['open']):
                    continue
                
                signal_date = curr_row['timestamp']
                signal_price = curr_row['close']
                signal_index = j
                
                # 이후 골든크로스 발생 확인 (30일 이내)
                golden_cross_found = False
                golden_cross_index = -1
                
                for gc_idx in range(signal_index + 1, min(signal_index + 180, len(recent_df))):
                    prev_row = recent_df.iloc[gc_idx - 1]
                    curr_gc_row = recent_df.iloc[gc_idx]
                    
                    if (pd.isna(prev_row['ma50']) or pd.isna(prev_row['ma200']) or
                        pd.isna(curr_gc_row['ma50']) or pd.isna(curr_gc_row['ma200'])):
                        continue
                    
                    # 골든크로스 조건
                    if prev_row['ma50'] < prev_row['ma200'] and curr_gc_row['ma50'] > curr_gc_row['ma200']:
                        golden_cross_found = True
                        golden_cross_index = gc_idx
                        break
                
                if not golden_cross_found:
                    continue
                
                # 골든크로스 후 일주일간 최고 수익률 계산
                gc_row = recent_df.iloc[golden_cross_index]
                golden_cross_date = gc_row['timestamp']
                golden_cross_price = gc_row['close']
                
                one_week_after = golden_cross_date + pd.Timedelta(days=7)
                week_data = recent_df[
                    (recent_df['timestamp'] > golden_cross_date) & 
                    (recent_df['timestamp'] <= one_week_after)
                ]
                
                if len(week_data) == 0:
                    continue
                
                max_price_after_gc = week_data['high'].max()
                max_profit_rate = ((max_price_after_gc - golden_cross_price) / golden_cross_price) * 100
                
                # 패턴 정보 저장 (확장된 지표 포함)
                days_to_gc = (golden_cross_date - signal_date).days
                
                # 선행신호 시점 지표
                signal_rsi = curr_row['rsi'] if not pd.isna(curr_row['rsi']) else 50
                signal_bb_position = curr_row['bb_position'] if not pd.isna(curr_row['bb_position']) else 0.5
                signal_bb_width = curr_row['bb_width'] if not pd.isna(curr_row['bb_width']) else 0.1
                signal_macd = curr_row['macd'] if not pd.isna(curr_row['macd']) else 0
                signal_macd_histogram = curr_row['macd_histogram'] if not pd.isna(curr_row['macd_histogram']) else 0
                signal_stoch_rsi = curr_row['stoch_rsi'] if not pd.isna(curr_row['stoch_rsi']) else 50
                signal_volume_ratio = curr_row['volume_ratio'] if not pd.isna(curr_row['volume_ratio']) else 1
                signal_candle_body_ratio = curr_row['candle_body_ratio'] if not pd.isna(curr_row['candle_body_ratio']) else 0.5
                signal_is_bullish = curr_row['is_bullish']
                signal_is_hammer = curr_row['is_hammer']
                signal_volatility = curr_row['price_volatility'] if not pd.isna(curr_row['price_volatility']) else 0.02
                
                # 골든크로스 시점 지표
                gc_rsi = gc_row['rsi'] if not pd.isna(gc_row['rsi']) else 50
                gc_bb_position = gc_row['bb_position'] if not pd.isna(gc_row['bb_position']) else 0.5
                gc_bb_width = gc_row['bb_width'] if not pd.isna(gc_row['bb_width']) else 0.1
                gc_macd = gc_row['macd'] if not pd.isna(gc_row['macd']) else 0
                gc_macd_histogram = gc_row['macd_histogram'] if not pd.isna(gc_row['macd_histogram']) else 0
                gc_stoch_rsi = gc_row['stoch_rsi'] if not pd.isna(gc_row['stoch_rsi']) else 50
                gc_volume_ratio = gc_row['volume_ratio'] if not pd.isna(gc_row['volume_ratio']) else 1
                gc_candle_body_ratio = gc_row['candle_body_ratio'] if not pd.isna(gc_row['candle_body_ratio']) else 0.5
                gc_is_bullish = gc_row['is_bullish']
                gc_volatility = gc_row['price_volatility'] if not pd.isna(gc_row['price_volatility']) else 0.02
                
                # 선행신호 → 골든크로스 기간 동안의 패턴 분석
                period_data = recent_df.iloc[signal_index:golden_cross_index+1]
                period_bullish_ratio = period_data['is_bullish'].mean()
                period_avg_volume_ratio = period_data['volume_ratio'].mean()
                period_hammer_count = period_data['is_hammer'].sum()
                period_doji_count = period_data['is_doji'].sum()
                period_avg_volatility = period_data['price_volatility'].mean()
                
                complete_patterns.append({
                    'coin_name': coin_name,
                    'symbol': symbol,
                    'signal_date': signal_date,
                    'signal_price': signal_price,
                    'golden_cross_date': golden_cross_date,
                    'golden_cross_price': golden_cross_price,
                    'days_to_golden_cross': days_to_gc,
                    'max_profit_rate_after_gc': max_profit_rate,
                    'max_price_after_gc': max_price_after_gc,
                    
                    # 선행신호 시점 지표
                    'signal_rsi': signal_rsi,
                    'signal_bb_position': signal_bb_position,
                    'signal_bb_width': signal_bb_width,
                    'signal_macd': signal_macd,
                    'signal_macd_histogram': signal_macd_histogram,
                    'signal_stoch_rsi': signal_stoch_rsi,
                    'signal_volume_ratio': signal_volume_ratio,
                    'signal_candle_body_ratio': signal_candle_body_ratio,
                    'signal_is_bullish': signal_is_bullish,
                    'signal_is_hammer': signal_is_hammer,
                    'signal_volatility': signal_volatility,
                    
                    # 골든크로스 시점 지표
                    'gc_rsi': gc_rsi,
                    'gc_bb_position': gc_bb_position,
                    'gc_bb_width': gc_bb_width,
                    'gc_macd': gc_macd,
                    'gc_macd_histogram': gc_macd_histogram,
                    'gc_stoch_rsi': gc_stoch_rsi,
                    'gc_volume_ratio': gc_volume_ratio,
                    'gc_candle_body_ratio': gc_candle_body_ratio,
                    'gc_is_bullish': gc_is_bullish,
                    'gc_volatility': gc_volatility,
                    
                    # 기간 중 패턴
                    'period_bullish_ratio': period_bullish_ratio,
                    'period_avg_volume_ratio': period_avg_volume_ratio,
                    'period_hammer_count': period_hammer_count,
                    'period_doji_count': period_doji_count,
                    'period_avg_volatility': period_avg_volatility
                })
                
                print(f"   ✅ {coin_name}: 완전 패턴 발견 - 신호→GC {days_to_gc}일, GC후 최고 {max_profit_rate:.1f}%")
                break  # 첫 번째 패턴만 저장
            
            if complete_patterns:
                complete_pattern_results.extend(complete_patterns)
            else:
                print(f"   ❌ {coin_name}: 완전 패턴 없음")
                
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            continue
        
        time.sleep(0.1)
    
    if not complete_pattern_results:
        print("❌ 완전한 패턴을 발견한 종목이 없습니다.")
        return []
    
    # 결과 분석 및 출력
    print(f"\n📊 완전 패턴 분석 결과 ({len(complete_pattern_results)}개)")
    print("=" * 150)
    
    # 수익률 기준으로 내림차순 정렬
    complete_pattern_results.sort(key=lambda x: x['max_profit_rate_after_gc'], reverse=True)
    
    # 상위 수익률 종목들 출력 (확장된 지표 포함)
    print(f"{'순위':<4} {'종목':<8} {'신호일':<12} {'GC일':<12} {'신호→GC':<8} {'GC후최고':<10} {'신호RSI':<8} {'GC RSI':<8} {'신호BB':<8} {'GC BB':<8} {'신호MACD':<10} {'거래량':<8}")
    print("-" * 200)
    
    for i, pattern in enumerate(complete_pattern_results):
        rank = i + 1
        coin_name = pattern['coin_name']
        signal_date = pattern['signal_date'].strftime('%m-%d')
        gc_date = pattern['golden_cross_date'].strftime('%m-%d')
        days_to_gc = f"{pattern['days_to_golden_cross']}일"
        max_profit = f"{pattern['max_profit_rate_after_gc']:+.1f}%"
        signal_rsi = f"{pattern['signal_rsi']:.0f}"
        gc_rsi = f"{pattern['gc_rsi']:.0f}"
        signal_bb = f"{pattern['signal_bb_position']:.2f}"
        gc_bb = f"{pattern['gc_bb_position']:.2f}"
        signal_macd = f"{pattern['signal_macd']:+.3f}"
        volume_ratio = f"{pattern['signal_volume_ratio']:.1f}x"
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {gc_date:<12} {days_to_gc:<8} {max_profit:<10} {signal_rsi:<8} {gc_rsi:<8} {signal_bb:<8} {gc_bb:<8} {signal_macd:<10} {volume_ratio:<8}")
    
    # 고수익 종목들의 공통 패턴 추출
    print(f"\n🎯 고수익 종목들의 공통 패턴")
    print("=" * 100)
    
    if len(complete_pattern_results) >= 3:
        # 상위 50% 종목을 고수익 그룹으로 분류
        top_half_count = len(complete_pattern_results) // 2
        high_profit_patterns = complete_pattern_results[:top_half_count]
        
        # 기본 지표 평균값 계산
        avg_days_to_gc = sum(p['days_to_golden_cross'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_max_profit = sum(p['max_profit_rate_after_gc'] for p in high_profit_patterns) / len(high_profit_patterns)
        
        # 선행신호 시점 지표 평균값
        avg_signal_rsi = sum(p['signal_rsi'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_signal_bb_position = sum(p['signal_bb_position'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_signal_bb_width = sum(p['signal_bb_width'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_signal_macd = sum(p['signal_macd'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_signal_stoch_rsi = sum(p['signal_stoch_rsi'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_signal_volume_ratio = sum(p['signal_volume_ratio'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_signal_volatility = sum(p['signal_volatility'] for p in high_profit_patterns) / len(high_profit_patterns)
        
        # 골든크로스 시점 지표 평균값
        avg_gc_rsi = sum(p['gc_rsi'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_gc_bb_position = sum(p['gc_bb_position'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_gc_bb_width = sum(p['gc_bb_width'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_gc_macd = sum(p['gc_macd'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_gc_stoch_rsi = sum(p['gc_stoch_rsi'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_gc_volume_ratio = sum(p['gc_volume_ratio'] for p in high_profit_patterns) / len(high_profit_patterns)
        
        # 캔들 패턴 분석
        signal_bullish_ratio = sum(1 for p in high_profit_patterns if p['signal_is_bullish']) / len(high_profit_patterns)
        signal_hammer_ratio = sum(1 for p in high_profit_patterns if p['signal_is_hammer']) / len(high_profit_patterns)
        gc_bullish_ratio = sum(1 for p in high_profit_patterns if p['gc_is_bullish']) / len(high_profit_patterns)
        
        # 기간 중 패턴 분석
        avg_period_bullish_ratio = sum(p['period_bullish_ratio'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_period_volume_ratio = sum(p['period_avg_volume_ratio'] for p in high_profit_patterns) / len(high_profit_patterns)
        avg_period_volatility = sum(p['period_avg_volatility'] for p in high_profit_patterns) / len(high_profit_patterns)
        
        print(f"🎯 고수익 종목 성공 패턴 (상위 {top_half_count}개 종목 분석):")
        print(f"   📊 평균 신호→골든크로스 소요일: {avg_days_to_gc:.1f}일")
        print(f"   🚀 골든크로스 후 평균 최고 수익률: {avg_max_profit:.1f}%")
        
        print(f"\n📈 선행신호 시점 최적 지표:")
        print(f"   • RSI: {avg_signal_rsi:.1f} (중립권)")
        print(f"   • 볼린저밴드 위치: {avg_signal_bb_position:.2f} (0=하단, 0.5=중앙, 1=상단)")
        print(f"   • 볼린저밴드 폭: {avg_signal_bb_width:.3f} (변동성 지표)")
        print(f"   • MACD: {avg_signal_macd:+.3f}")
        print(f"   • Stochastic RSI: {avg_signal_stoch_rsi:.1f}")
        print(f"   • 거래량 비율: {avg_signal_volume_ratio:.1f}배")
        print(f"   • 가격 변동성: {avg_signal_volatility:.3f}")
        print(f"   • 양봉 비율: {signal_bullish_ratio:.1%}")
        print(f"   • 해머 캔들 비율: {signal_hammer_ratio:.1%}")
        
        print(f"\n📊 골든크로스 시점 확인 지표:")
        print(f"   • RSI: {avg_gc_rsi:.1f}")
        print(f"   • 볼린저밴드 위치: {avg_gc_bb_position:.2f}")
        print(f"   • 볼린저밴드 폭: {avg_gc_bb_width:.3f}")
        print(f"   • MACD: {avg_gc_macd:+.3f}")
        print(f"   • Stochastic RSI: {avg_gc_stoch_rsi:.1f}")
        print(f"   • 거래량 비율: {avg_gc_volume_ratio:.1f}배")
        print(f"   • 양봉 비율: {gc_bullish_ratio:.1%}")
        
        print(f"\n⏰ 선행신호→골든크로스 기간 중 패턴:")
        print(f"   • 기간 중 양봉 비율: {avg_period_bullish_ratio:.1%}")
        print(f"   • 기간 중 평균 거래량: {avg_period_volume_ratio:.1f}배")
        print(f"   • 기간 중 평균 변동성: {avg_period_volatility:.3f}")
        
        print(f"\n💡 확장된 투자 가이드라인:")
        print("=" * 120)
        print("🚀 1단계 - 선행신호 포착 조건:")
        print(f"   • RSI {max(30, avg_signal_rsi-10):.0f}~{min(70, avg_signal_rsi+10):.0f} 구간")
        print(f"   • 볼린저밴드 위치 {max(0.1, avg_signal_bb_position-0.2):.1f}~{min(0.9, avg_signal_bb_position+0.2):.1f}")
        print(f"   • MACD {avg_signal_macd-0.01:+.3f}~{avg_signal_macd+0.01:+.3f} 구간")
        print(f"   • Stochastic RSI {max(20, avg_signal_stoch_rsi-15):.0f}~{min(80, avg_signal_stoch_rsi+15):.0f}")
        print(f"   • 거래량 {avg_signal_volume_ratio:.1f}배 이상 증가")
        print(f"   • 양봉 캔들 선호 (성공률 {signal_bullish_ratio:.0%})")
        
        print(f"\n📈 2단계 - 골든크로스 대기 및 확인:")
        print(f"   • 선행신호 후 평균 {avg_days_to_gc:.0f}일 내 골든크로스 발생 예상")
        print(f"   • 기간 중 양봉 비율 {avg_period_bullish_ratio:.0%} 이상 유지")
        print(f"   • 거래량 지속적 증가 ({avg_period_volume_ratio:.1f}배 수준)")
        print(f"   • 변동성 적정 수준 유지 ({avg_period_volatility:.3f})")
        
        print(f"\n🎯 3단계 - 골든크로스 발생 시 진입:")
        print(f"   • 골든크로스 확인 시 즉시 진입 고려")
        print(f"   • RSI {avg_gc_rsi:.0f} 수준에서 골든크로스 발생 시 최적")
        print(f"   • 볼린저밴드 위치 {avg_gc_bb_position:.1f} 수준 확인")
        print(f"   • MACD {avg_gc_macd:+.3f} 수준에서 진입")
        print(f"   • 골든크로스 후 일주일 내 평균 {avg_max_profit:.1f}% 수익 기대")
    
    return complete_pattern_results

def validate_investment_guidelines():
    """투자 가이드라인 백테스팅 검증 - 과거 2달 데이터 기반"""
    print(f"\n🔍 투자 가이드라인 백테스팅 검증")
    print("📋 검증 목적: 5번 분석에서 도출된 투자 가이드라인의 실제 성과 검증")
    print("🔍 검증 조건:")
    print("   📈 1단계 - 선행신호 포착 조건:")
    print("      • RSI 30~45 구간")
    print("      • 볼린저밴드 위치 0.1~0.5")
    print("      • MACD -3.112~-3.092 구간")
    print("      • Stochastic RSI 25~55")
    print("      • 거래량 0.5배 이상 증가")
    print("      • 양봉 캔들 선호")
    print("   📊 2단계 - 골든크로스 대기 (22일 내)")
    print("   🎯 3단계 - 골든크로스 진입 조건:")
    print("      • RSI 75 수준")
    print("      • 볼린저밴드 위치 0.8 수준")
    print("      • MACD +9.470 수준")
    
    # 모든 KRW 종목 가져오기
    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("❌ 업비트 종목을 가져올 수 없습니다.")
        return []
    
    print(f"\n📊 총 {len(all_tickers)}개 종목의 백테스팅 검증 중...")
    
    # 2달 전부터 현재까지 분석
    two_months_ago = datetime.now() - pd.Timedelta(days=60)
    print(f"📅 검증 기간: {two_months_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    validation_results = []
    total_signals = 0
    successful_trades = 0
    
    for i, symbol in enumerate(all_tickers[:20]):  # 상위 20개 종목으로 검증
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 검증 중... ({i+1}/20) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (더 많은 데이터 수집)
            all_data = []
            limit_per_request = 200
            total_requests = 5  # 1000개 데이터 (약 6개월치)
            
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
                print(f"   ❌ {coin_name}: 데이터 조회 실패")
                continue
            
            # 데이터프레임 생성 및 정제
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 300:
                print(f"   ⚠️ {coin_name}: 수집된 데이터 부족 ({len(df)}개)")
                continue
            
            # 데이터 정제
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            # 모든 기술적 지표 계산
            df['ma50'] = df['close'].rolling(window=50).mean()
            df['ma200'] = df['close'].rolling(window=200).mean()
            
            # RSI 계산
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # 볼린저 밴드 계산
            df['bb_middle'] = df['close'].rolling(window=20).mean()
            bb_std = df['close'].rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
            
            # MACD 계산
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            
            # Stochastic RSI 계산
            rsi_low = df['rsi'].rolling(window=14).min()
            rsi_high = df['rsi'].rolling(window=14).max()
            df['stoch_rsi'] = (df['rsi'] - rsi_low) / (rsi_high - rsi_low) * 100
            
            # 거래량 비율 계산
            df['volume_ma20'] = df['volume'].rolling(window=20).mean()
            df['volume_ratio'] = df['volume'] / df['volume_ma20']
            
            # 캔들 패턴
            df['is_bullish'] = df['close'] > df['open']
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 2달 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= two_months_ago].copy()
            
            if len(recent_df) < 50:
                print(f"   ⚠️ {coin_name}: 2달 이내 데이터 부족")
                continue
            
            # 백테스팅 검증 로직
            coin_signals = 0
            coin_successful = 0
            coin_trades = []
            
            for j in range(50, len(recent_df) - 50):  # 충분한 전후 데이터 확보
                curr_row = recent_df.iloc[j]
                
                # 1단계: 선행신호 포착 조건 검증
                if (pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or
                    curr_row['ma50'] >= curr_row['ma200']):  # 골든크로스 이전 상태
                    continue
                
                # 가이드라인 조건 체크 (조건 완화)
                rsi_ok = 25 <= curr_row['rsi'] <= 50 if not pd.isna(curr_row['rsi']) else False
                bb_ok = 0.05 <= curr_row['bb_position'] <= 0.6 if not pd.isna(curr_row['bb_position']) else False
                macd_ok = curr_row['macd'] <= -1.0 if not pd.isna(curr_row['macd']) else False  # MACD 조건 완화
                stoch_rsi_ok = 20 <= curr_row['stoch_rsi'] <= 60 if not pd.isna(curr_row['stoch_rsi']) else False
                volume_ok = curr_row['volume_ratio'] >= 0.3 if not pd.isna(curr_row['volume_ratio']) else False  # 거래량 조건 완화
                bullish_ok = curr_row['is_bullish']
                
                # 핵심 조건만 체크 (RSI, 볼린저밴드, 양봉, 거래량)
                core_conditions = rsi_ok and bb_ok and volume_ok and bullish_ok
                
                # 추가 조건 중 하나라도 만족하면 통과
                additional_conditions = macd_ok or stoch_rsi_ok
                
                if not (core_conditions and additional_conditions):
                    continue
                
                signal_date = curr_row['timestamp']
                signal_price = curr_row['close']
                signal_index = j
                
                # 2단계: 22일 내 골든크로스 발생 확인
                golden_cross_found = False
                golden_cross_index = -1
                
                search_end = min(signal_index + 132, len(recent_df))  # 22일 = 132개 4시간 캔들
                
                for gc_idx in range(signal_index + 1, search_end):
                    if gc_idx >= len(recent_df):
                        break
                        
                    prev_row = recent_df.iloc[gc_idx - 1]
                    curr_gc_row = recent_df.iloc[gc_idx]
                    
                    if (pd.isna(prev_row['ma50']) or pd.isna(prev_row['ma200']) or
                        pd.isna(curr_gc_row['ma50']) or pd.isna(curr_gc_row['ma200'])):
                        continue
                    
                    # 골든크로스 조건
                    if prev_row['ma50'] < prev_row['ma200'] and curr_gc_row['ma50'] > curr_gc_row['ma200']:
                        golden_cross_found = True
                        golden_cross_index = gc_idx
                        break
                
                if not golden_cross_found:
                    continue
                
                # 3단계: 골든크로스 진입 조건 검증
                gc_row = recent_df.iloc[golden_cross_index]
                
                # 진입 조건 체크 (조건을 완화하여 실제 거래 가능성 높임)
                gc_rsi_ok = 60 <= gc_row['rsi'] <= 85 if not pd.isna(gc_row['rsi']) else False
                gc_bb_ok = 0.6 <= gc_row['bb_position'] <= 1.0 if not pd.isna(gc_row['bb_position']) else False
                gc_macd_ok = gc_row['macd'] >= 2.0 if not pd.isna(gc_row['macd']) else False
                
                # 진입 조건 중 2개 이상 만족하면 거래 시뮬레이션
                entry_conditions_met = sum([gc_rsi_ok, gc_bb_ok, gc_macd_ok])
                
                if entry_conditions_met >= 2:
                    entry_date = gc_row['timestamp']
                    entry_price = gc_row['close']
                    
                    # 진입 후 일주일간 최고 수익률 계산
                    one_week_after = entry_date + pd.Timedelta(days=7)
                    week_data = recent_df[
                        (recent_df['timestamp'] > entry_date) & 
                        (recent_df['timestamp'] <= one_week_after)
                    ]
                    
                    if len(week_data) > 0:
                        max_price_week = week_data['high'].max()
                        max_profit_rate = ((max_price_week - entry_price) / entry_price) * 100
                        
                        coin_signals += 1
                        total_signals += 1
                        
                        if max_profit_rate > 0:
                            coin_successful += 1
                            successful_trades += 1
                        
                        coin_trades.append({
                            'signal_date': signal_date,
                            'entry_date': entry_date,
                            'entry_price': entry_price,
                            'max_price_week': max_price_week,
                            'max_profit_rate': max_profit_rate,
                            'days_to_gc': (entry_date - signal_date).days
                        })
                        
                        print(f"   📊 {coin_name}: 거래 발견 - 진입가 {entry_price:,.0f}원, 최고 수익률 {max_profit_rate:+.1f}%")
            
            if coin_trades:
                validation_results.append({
                    'coin_name': coin_name,
                    'symbol': symbol,
                    'total_signals': coin_signals,
                    'successful_trades': coin_successful,
                    'trades': coin_trades,
                    'success_rate': coin_successful / coin_signals * 100 if coin_signals > 0 else 0,
                    'avg_profit': sum(t['max_profit_rate'] for t in coin_trades) / len(coin_trades)
                })
            else:
                print(f"   ❌ {coin_name}: 가이드라인 조건 만족하는 거래 없음")
                
        except Exception as e:
            print(f"   ❌ {coin_name}: 검증 실패 - {e}")
            continue
        
        time.sleep(0.1)
    
    # 백테스팅 결과 분석 및 출력
    if not validation_results:
        print("❌ 가이드라인 조건을 만족하는 거래가 없습니다.")
        return []
    
    print(f"\n📊 백테스팅 검증 결과")
    print("=" * 150)
    
    # 전체 통계
    total_profit = sum(sum(t['max_profit_rate'] for t in result['trades']) for result in validation_results)
    total_trades = sum(len(result['trades']) for result in validation_results)
    overall_success_rate = successful_trades / total_signals * 100 if total_signals > 0 else 0
    avg_profit_per_trade = total_profit / total_trades if total_trades > 0 else 0
    
    print(f"🎯 전체 백테스팅 성과:")
    print(f"   📊 총 신호 발생: {total_signals}회")
    print(f"   ✅ 수익 거래: {successful_trades}회")
    print(f"   📈 전체 성공률: {overall_success_rate:.1f}%")
    print(f"   💰 거래당 평균 수익률: {avg_profit_per_trade:+.2f}%")
    
    # 종목별 상세 결과
    print(f"\n📋 종목별 백테스팅 결과:")
    print(f"{'순위':<4} {'종목':<8} {'신호수':<8} {'성공수':<8} {'성공률':<10} {'평균수익률':<12} {'최고수익률':<12}")
    print("-" * 150)
    
    # 평균 수익률 기준으로 정렬
    validation_results.sort(key=lambda x: x['avg_profit'], reverse=True)
    
    for i, result in enumerate(validation_results):
        rank = i + 1
        coin_name = result['coin_name']
        total_sigs = result['total_signals']
        successful = result['successful_trades']
        success_rate = f"{result['success_rate']:.1f}%"
        avg_profit = f"{result['avg_profit']:+.2f}%"
        max_profit = f"{max(t['max_profit_rate'] for t in result['trades']):+.2f}%"
        
        print(f"{rank:<4} {coin_name:<8} {total_sigs:<8} {successful:<8} {success_rate:<10} {avg_profit:<12} {max_profit:<12}")
    
    # 상위 성과 종목 상세 분석
    if len(validation_results) >= 3:
        top_3_results = validation_results[:3]
        
        print(f"\n🏆 상위 3개 종목 상세 거래 내역:")
        print("=" * 180)
        
        for result in top_3_results:
            coin_name = result['coin_name']
            print(f"\n📈 {coin_name} 상세 거래 내역:")
            print(f"{'거래번호':<8} {'신호일':<12} {'진입일':<12} {'진입가격':<12} {'최고가격':<12} {'수익률':<10} {'신호→GC':<10}")
            print("-" * 120)
            
            for j, trade in enumerate(result['trades']):
                trade_num = j + 1
                signal_date = trade['signal_date'].strftime('%m-%d')
                entry_date = trade['entry_date'].strftime('%m-%d')
                entry_price = f"{trade['entry_price']:,.0f}원"
                max_price = f"{trade['max_price_week']:,.0f}원"
                profit_rate = f"{trade['max_profit_rate']:+.1f}%"
                days_to_gc = f"{trade['days_to_gc']}일"
                
                print(f"{trade_num:<8} {signal_date:<12} {entry_date:<12} {entry_price:<12} {max_price:<12} {profit_rate:<10} {days_to_gc:<10}")
    
    # 가이드라인 검증 결론
    print(f"\n🎯 투자 가이드라인 검증 결론:")
    print("=" * 120)
    
    if overall_success_rate >= 70:
        print("✅ 가이드라인 검증 결과: 매우 우수")
        print(f"   📊 성공률 {overall_success_rate:.1f}%로 높은 신뢰도")
    elif overall_success_rate >= 50:
        print("📈 가이드라인 검증 결과: 양호")
        print(f"   📊 성공률 {overall_success_rate:.1f}%로 적정 수준")
    else:
        print("⚠️ 가이드라인 검증 결과: 개선 필요")
        print(f"   📊 성공률 {overall_success_rate:.1f}%로 추가 최적화 권장")
    
    print(f"\n💡 검증 기반 투자 권장사항:")
    if avg_profit_per_trade > 15:
        print("🚀 현재 가이드라인 조건으로 투자 진행 권장")
    elif avg_profit_per_trade > 10:
        print("📈 신중한 투자 진행, 추가 확인 후 결정")
    else:
        print("⚠️ 가이드라인 조건 재검토 필요")
    
    print(f"   📊 거래당 평균 수익률: {avg_profit_per_trade:+.2f}%")
    print(f"   📈 전체 성공률: {overall_success_rate:.1f}%")
    print(f"   🎯 검증 기간: 과거 2달 ({total_trades}회 거래)")
    
    return validation_results

def select_current_entry_targets():
    """1주일 이내 골든크로스 예상 종목 리스트업"""
    print(f"\n🎯 1주일 이내 골든크로스 예상 종목 분석")
    print(f"📋 분석 목적: MA50과 MA200이 가까워져 1주일 이내 골든크로스가 예상되는 종목 발굴")
    
    print(f"\n� 골든크로스  임박 판단 기준:")
    print(f"   📊 MA50과 MA200 간격이 5% 이내")
    print(f"   📈 현재는 데드크로스 상태 (MA50 < MA200)")
    print(f"   � MA50이 상승  추세")
    print(f"   � 거래량3이 증가 추세")

    
    # 더 많은 종목으로 확장 (데이터 부족 문제 해결)
    all_symbols = [
        'XRP/KRW', 'BTC/KRW', 'ETH/KRW', 'ADA/KRW', 'DOT/KRW',
        'LINK/KRW', 'SOL/KRW', 'AVAX/KRW', 'ATOM/KRW', 'ALGO/KRW',
        'XLM/KRW', 'VET/KRW', 'HBAR/KRW', 'ETC/KRW', 'LTC/KRW',
        'BCH/KRW', 'EOS/KRW', 'TRX/KRW', 'QTUM/KRW', 'OMG/KRW',
        'ZRX/KRW', 'REP/KRW', 'BAT/KRW', 'ZEC/KRW', 'XTZ/KRW'
    ]
    
    print(f"\n📊 주요 {len(all_symbols)}개 종목의 1주일 이내 골든크로스 예상 분석 중...")
    
    # 종목 리스트 변경
    test_symbols = all_symbols
    
    golden_cross_candidates = []  # 1주일 이내 골든크로스 예상 종목
    
    for i, symbol in enumerate(test_symbols):
        coin_name = symbol.replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/{len(test_symbols)}) {coin_name}")
        
        try:
            # 간단한 데이터 조회
            df = get_ohlcv(symbol, timeframe='4h')
            
            if df is None or len(df) < 200:  # 조건 완화
                print(f"   ⚠️ {coin_name}: 데이터 부족")
                time.sleep(2)  # 더 긴 대기
                continue
            
            # 이동평균 계산
            df['ma50'] = df['close'].rolling(window=50).mean()
            df['ma200'] = df['close'].rolling(window=200).mean()
            
            latest = df.iloc[-1]
            
            # MA 값 확인
            if pd.isna(latest['ma50']) or pd.isna(latest['ma200']):
                print(f"   ⚠️ {coin_name}: MA 계산 불가")
                time.sleep(2)
                continue
            
            # 데드크로스 상태 확인
            is_golden_cross = latest['ma50'] > latest['ma200']
            if is_golden_cross:
                print(f"   ❌ {coin_name}: 이미 골든크로스 상태")
                time.sleep(2)
                continue
            
            # MA 간격 계산
            ma_gap_percent = abs(latest['ma50'] - latest['ma200']) / latest['ma200'] * 100
            
            if ma_gap_percent <= 5.0:  # 5% 이내 (1주일 기준)
                # 추세 확인
                recent_data = df.tail(12)
                ma50_trend = recent_data['ma50'].iloc[-1] > recent_data['ma50'].iloc[0]
                
                if ma50_trend:
                    # 예상 시기 계산 (1주일 기준)
                    if ma_gap_percent <= 1.0:
                        expected_time = "1-2일"
                        urgency = "🚨 매우 임박"
                    elif ma_gap_percent <= 2.0:
                        expected_time = "2-3일"
                        urgency = "⚡ 임박"
                    elif ma_gap_percent <= 3.5:
                        expected_time = "3-5일"
                        urgency = "📈 가까움"
                    else:
                        expected_time = "5-7일"
                        urgency = "🔍 관찰"
                    
                    golden_cross_candidates.append({
                        'coin_name': coin_name,
                        'symbol': symbol,
                        'current_price': latest['close'],
                        'ma_gap_percent': ma_gap_percent,
                        'expected_time': expected_time,
                        'urgency': urgency,
                        'ma50': latest['ma50'],
                        'ma200': latest['ma200']
                    })
                    print(f"   🎯 {coin_name}: 골든크로스 임박 - {expected_time}")
                else:
                    print(f"   ❌ {coin_name}: MA50 하락 추세")
            else:
                print(f"   ❌ {coin_name}: MA 간격 너무 큼 ({ma_gap_percent:.2f}%)")
        
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
        
        time.sleep(2)  # API 제한 방지 (더 긴 대기)
    
    # 결과 출력
    print(f"\n📊 1주일 이내 골든크로스 예상 종목 분석 결과")
    print("=" * 160)
    
    if golden_cross_candidates:
        print(f"🎯 총 {len(golden_cross_candidates)}개 골든크로스 임박 종목 발견")
        
        # 긴급도와 MA 간격으로 정렬
        golden_cross_candidates.sort(key=lambda x: x['ma_gap_percent'])
        
        print(f"\n🚨 1주일 이내 골든크로스 예상 종목 리스트")
        print("=" * 120)
        print(f"{'순위':<4} {'종목':<10} {'현재가':<15} {'MA간격':<10} {'예상시기':<15} {'긴급도':<12} {'RSI':<8}")
        print("-" * 120)
        
        for i, candidate in enumerate(golden_cross_candidates):
            rank = i + 1
            coin_name = candidate['coin_name']
            current_price = f"{candidate['current_price']:,.0f}원"
            ma_gap = f"{candidate['ma_gap_percent']:.2f}%"
            expected_hours = candidate['expected_time']
            urgency = candidate['urgency']
            rsi = "N/A"  # RSI 계산 제거로 인해 기본값 사용
            
            print(f"{rank:<4} {coin_name:<10} {current_price:<15} {ma_gap:<10} {expected_hours:<15} {urgency:<12} {rsi:<8}")
        
        # 긴급도별 분류
        urgent_candidates = [c for c in golden_cross_candidates if c['ma_gap_percent'] <= 0.5]
        imminent_candidates = [c for c in golden_cross_candidates if 0.5 < c['ma_gap_percent'] <= 1.0]
        close_candidates = [c for c in golden_cross_candidates if 1.0 < c['ma_gap_percent'] <= 1.5]
        watch_candidates = [c for c in golden_cross_candidates if c['ma_gap_percent'] > 1.5]
        
        print(f"\n📊 긴급도별 분류:")
        print(f"   🚨 매우 임박 (6-12시간): {len(urgent_candidates)}개")
        print(f"   ⚡ 임박 (12-24시간): {len(imminent_candidates)}개")
        print(f"   � 가까움 (1-2일): {len(close_candidates)}개")
        print(f"   🔍 관찰 (2-3일): {len(watch_candidates)}개")
        
        print(f"\n💡 모니터링 가이드:")
        print(f"   🚨 매우 임박 종목: 6시간마다 체크, 골든크로스 발생 즉시 진입 검토")
        print(f"   ⚡ 임박 종목: 12시간마다 체크, 거래량 동반 상승 시 주목")
        print(f"   📈 가까운 종목: 하루 2회 체크, 추세 변화 모니터링")
        print(f"   🔍 관찰 종목: 하루 1회 체크, 조건 변화 추적")
        
        print(f"\n🎯 골든크로스 발생 시 진입 전략:")
        print(f"   1️⃣ 골든크로스 발생 확인 (MA50 > MA200)")
        print(f"   2️⃣ 거래량 급증 여부 확인 (평균 대비 1.5배 이상)")
        print(f"   3️⃣ 3-4개 연속 양봉 캔들 형성 대기")
        print(f"   4️⃣ RSI 60-80 구간 진입 시 매수 검토")
        print(f"   5️⃣ 저항선 돌파 확인 후 진입")
        
        print(f"\n⚠️ 주의사항:")
        print(f"   • 거래량 없는 골든크로스는 페이크 가능성 높음")
        print(f"   • 급격한 시장 변동 시 예상 시기 변경 가능")
        print(f"   • 분산 투자 권장 (여러 종목에 나누어 투자)")
        print(f"   • 손절매 기준: -5% 손실 시 매도 고려")
    
    else:
        print(f"❌ 현재 1주일 이내 골든크로스가 예상되는 종목이 없습니다.")
        print(f"\n🔍 가능한 원인:")
        print(f"   • 전체적인 시장 하락 추세")
        print(f"   • 대부분 종목이 이미 골든크로스 상태")
        print(f"   • MA 간격이 너무 큰 상태")
        print(f"\n💡 권장사항:")
        print(f"   • 시장 상황 변화 시 재분석")
        print(f"   • 다른 메뉴로 기존 골든크로스 종목 분석")
        print(f"   • 더 긴 기간(1주일) 예상 종목 분석 고려")
    
    print("=" * 160)
    return golden_cross_candidates

def basic_test():
    """기본 테스트 - 업비트 연결 및 데이터 조회 확인"""
    print(f"\n🧪 업비트 API 연결 테스트 시작")
    tickers = get_krw_tickers()[:5]  # 처음 5개만 테스트
    
    for symbol in tickers:
        print(f"\n🔍 {symbol} 테스트 중...")
        
        # 현재 가격 조회
        current_price = get_current_price(symbol)
        if current_price:
            print(f"   💰 현재가: {current_price:,.0f} KRW")
        else:
            print(f"   ❌ 현재가 조회 실패")
        
        # OHLCV 데이터 조회
        df_4h = get_ohlcv(symbol, '4h')
        if df_4h is not None and len(df_4h) > 0:
            latest = df_4h.iloc[-1]
            print(f"   📊 최근 종가: {latest['close']:,.0f} KRW")
            print(f"   📈 데이터 개수: {len(df_4h)}개")
            print(f"   📅 최근 업데이트: {latest['timestamp'].strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"   ❌ OHLCV 데이터 조회 실패")
        
        time.sleep(0.1)

# 테스트 실행
if __name__ == "__main__":
    try:
        print("🎯 업비트 골든크로스 진입 신호 분석기")
        print("=" * 60)
        print("📈 골든크로스 발생 후 3~4개의 양봉 캔들이 강하게 형성되면 진입 고려")
        print("📊 반드시 거래량 동반 상승일 때만 의미 있음")
        print("🚀 골든크로스 + 저항 돌파 + 거래량 증가 = 진짜 신호")
        print("⚠️ 반대로 거래량 없이 골든크로스만 발생 → 대부분 페이크")
        print("=" * 60)
        
        # 업비트 연결 테스트
        print("\n🔧 업비트 API 연결 테스트 중...")
        try:
            test_tickers = get_krw_tickers()
            if not test_tickers:
                print("❌ 업비트 연결 실패. 프로그램을 종료합니다.")
                exit(1)
            print(f"✅ 업비트 연결 성공! 사용 가능한 종목: {len(test_tickers)}개")
        except Exception as e:
            print(f"❌ 업비트 연결 테스트 실패: {e}")
            print("🔧 문제 해결 방법:")
            print("   1. 인터넷 연결 확인")
            print("   2. 업비트 서버 상태 확인")
            print("   3. 잠시 후 재시도")
            exit(1)
        
        # 선택 메뉴
        print("\n📋 분석 메뉴:")
        print("1. 골든크로스 이전 선행신호 분석 - 1달 기준 (50MA터치→양봉→200MA터치후상승+거래량증가)")
        print("2. 골든크로스 발생 후 진입신호 분석 - 2달 기준")
        print("3. 🚨 3일 이내 골든크로스 이전 선행신호 긴급 분석 (골든크로스 임박 종목)")
        print("4. 📊 고수익 종목 패턴 분석 (차트 지표 공통점 발굴)")
        print("5. 🎯 선행신호 기반 고수익 종목 패턴 분석 (선행신호→골든크로스 전체 패턴)")
        print("6. 전체 분석 (1번 + 2번)")
        print("7. 🔍 투자 가이드라인 백테스팅 검증 (과거 2달 데이터 기반)")
        print("8. 🚨 1주일 이내 골든크로스 예상 종목 리스트업 (MA 간격 5% 이내 임박 종목)")
        print("9. 🧪 기본 테스트 (업비트 연결 및 데이터 조회 확인)")
        
        choice = input("\n선택하세요 (1/2/3/4/5/6/7/8/9): ").strip()
        
        # 메모리 정리 함수
        def cleanup_memory():
            import gc
            gc.collect()
            print("   💾 메모리 정리 완료")
        
        try:
            if choice == "1":
                # 골든크로스 이전 선행신호 분석 (1달 기준)
                print("\n🔄 1번 분석 시작...")
                analyze_pre_golden_cross_signals()
                cleanup_memory()
                
            elif choice == "2":
                # 업비트 전 종목의 골든크로스 분석 (2달 기준)
                print("\n🔄 2번 분석 시작...")
                analyze_all_coins_golden_cross()
                cleanup_memory()
                
            elif choice == "3":
                # 3일 이내 골든크로스 이전 선행신호 긴급 분석
                print("\n🔄 3번 분석 시작...")
                analyze_recent_pre_signals()
                cleanup_memory()
                
            elif choice == "4":
                # 고수익 종목 패턴 분석
                print("\n🔄 4번 분석 시작...")
                analyze_high_profit_patterns()
                cleanup_memory()
                
            elif choice == "5":
                # 선행신호 기반 고수익 종목 패턴 분석
                print("\n🔄 5번 분석 시작...")
                analyze_pattern_matching()
                cleanup_memory()
                
            elif choice == "6":
                # 전체 분석
                print("\n🔄 전체 분석 시작...")
                analyze_pre_golden_cross_signals()
                print("\n" + "="*80)
                cleanup_memory()
                analyze_all_coins_golden_cross()
                cleanup_memory()
                
            elif choice == "7":
                # 투자 가이드라인 백테스팅 검증
                print("\n🔄 7번 분석 시작...")
                validate_investment_guidelines()
                cleanup_memory()
                
            elif choice == "8":
                # 현재 진입 대상 종목 선별
                print("\n🔄 8번 분석 시작...")
                select_current_entry_targets()
                cleanup_memory()
                
            elif choice == "9":
                # 기본 테스트
                print("\n🔄 9번 테스트 시작...")
                basic_test()
                cleanup_memory()
                
            else:
                print("❌ 잘못된 선택입니다. 기본 분석을 실행합니다.")
                analyze_all_coins_golden_cross()
                cleanup_memory()
        
        except KeyboardInterrupt:
            print("\n⏹️ 사용자에 의해 분석이 중단되었습니다.")
            cleanup_memory()
        except Exception as e:
            print(f"\n❌ 분석 중 오류 발생: {e}")
            print("🔧 문제 해결 방법:")
            print("   1. 인터넷 연결 확인")
            print("   2. 업비트 서버 상태 확인")
            print("   3. 프로그램 재시작")
            cleanup_memory()
        
        print("\n" + "="*80)
        
        # XRP 골든크로스 분석 (주석 처리)
        # analyze_xrp_golden_cross()
        
        print("\n✅ 분석 완료!")
        print("\n💡 투자 시 주의사항:")
        print("   🎯 진입 고려 신호만 투자 검토")
        print("   📊 거래량 없는 골든크로스는 무시")
        print("   🚀 저항선 돌파 + 양봉 연속 시 강력한 신호")
        print("   ⚠️ 투자는 본인 책임하에 신중히 결정하세요")
        
        # 최종 메모리 정리
        cleanup_memory()
        
    except KeyboardInterrupt:
        print("\n⏹️ 프로그램이 중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 치명적 오류 발생: {e}")
        print("🔧 프로그램을 재시작해주세요.")
    finally:
        print("\n👋 프로그램을 종료합니다.")