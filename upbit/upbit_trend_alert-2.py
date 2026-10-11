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

def get_ohlcv(symbol, timeframe='4h'):
    try:
        # 시간대별 데이터 개수 설정
        if timeframe == '4h':
            limit = 300
        else:  # 1h
            limit = 500
            
        data = upbit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"{symbol} {timeframe} OHLCV 가져오기 실패: {e}")
        return None

def get_current_price(symbol):
    """현재 가격 조회"""
    try:
        ticker = upbit.fetch_ticker(symbol)
        return ticker['last']
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
    
    for i, symbol in enumerate(all_tickers):
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/{len(all_tickers)}) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (XRP 분석과 동일한 방식으로 충분한 데이터 확보)
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
                    
                    time.sleep(0.05)  # 짧은 딜레이
                    
                except Exception as e:
                    break
            
            if not all_data:
                print(f"   ❌ {coin_name}: 데이터 조회 실패")
                continue
            
            # 데이터프레임 생성 및 정제
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            if len(df) < 250:
                print(f"   ⚠️ {coin_name}: 수집된 데이터 부족 ({len(df)}개)")
                continue
            
            # 데이터 정제
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0]
            df = df.reset_index(drop=True)
            
            if len(df) < 250:
                print(f"   ⚠️ {coin_name}: 정제 후 데이터 부족")
                continue
            
            # 이동평균 계산
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 2달 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= two_months_ago].copy()
            
            if len(recent_df) < 10:
                print(f"   ⚠️ {coin_name}: 2달 이내 데이터 부족")
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
                    
                    # 현재가 조회
                    current_price = get_current_price(symbol)
                    if current_price is None:
                        current_price = df_valid.iloc[-1]['close']  # 최신 종가 사용
                    
                    # 골든크로스 신호 신뢰성 분석
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
                # 가장 최근 골든크로스만 저장
                latest_golden_cross = golden_crosses[-1]
                golden_cross_results.append(latest_golden_cross)
                print(f"   ✅ {coin_name}: {latest_golden_cross['days_ago']}일 전 골든크로스")
            else:
                print(f"   ❌ {coin_name}: 2달 이내 골든크로스 없음")
        
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            continue
        
        # API 요청 제한 방지
        time.sleep(0.1)
    
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
        
        # 업비트 전 종목의 골든크로스 분석
        analyze_all_coins_golden_cross()
        
        print("\n" + "="*80)
        
        # XRP 골든크로스 분석 (주석 처리)
        # analyze_xrp_golden_cross()
        
        print("\n✅ 분석 완료!")
        print("\n💡 투자 시 주의사항:")
        print("   🎯 진입 고려 신호만 투자 검토")
        print("   📊 거래량 없는 골든크로스는 무시")
        print("   🚀 저항선 돌파 + 양봉 연속 시 강력한 신호")
        print("   ⚠️ 투자는 본인 책임하에 신중히 결정하세요")
    except KeyboardInterrupt:
        print("\n⏹️ 분석 중단됨")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")