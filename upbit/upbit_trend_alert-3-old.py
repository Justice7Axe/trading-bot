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

def analyze_pre_golden_cross_signals():
    """골든크로스 이전 선행 신호 탐지 (50MA 터치 → 양봉 → 200MA 터치 후 상승 + 거래량 증가)"""
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
        return
    
    print(f"\n📊 총 {len(all_tickers)}개 종목의 선행 신호 분석 중...")
    
    # 1달 전부터 현재까지 분석
    one_month_ago = datetime.now() - pd.Timedelta(days=30)
    print(f"📅 분석 기간: {one_month_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    pre_signal_results = []
    
    for i, symbol in enumerate(all_tickers):
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/{len(all_tickers)}) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (충분한 데이터 확보)
            all_data = []
            limit_per_request = 200
            total_requests = 6  # 1200개 데이터 (약 8개월치)
            
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
            
            if len(df) < 300:
                print(f"   ⚠️ {coin_name}: 정제 후 데이터 부족")
                continue
            
            # 이동평균 계산 (20MA, 50MA, 200MA)
            df['ma20'] = df['close'].rolling(window=20, center=False).mean()
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 1달 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= one_month_ago].copy()
            
            if len(recent_df) < 20:
                print(f"   ⚠️ {coin_name}: 1달 이내 데이터 부족")
                continue
            
            # 선행 신호 탐지
            pre_signals = []
            
            for j in range(10, len(recent_df) - 5):  # 충분한 전후 데이터 확보
                curr_row = recent_df.iloc[j]
                
                # 전제 조건: 아직 골든크로스 이전 (50MA < 200MA)
                if pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or pd.isna(curr_row['ma20']):
                    continue
                
                if curr_row['ma50'] >= curr_row['ma200']:  # 이미 골든크로스 상태면 제외
                    continue
                
                # 조건 1: 50MA 터치 확인 (캔들의 저가가 50MA 근처)
                ma50_touch_threshold = curr_row['ma50'] * 0.02  # 2% 오차 허용
                is_ma50_touch = (
                    abs(curr_row['low'] - curr_row['ma50']) <= ma50_touch_threshold or
                    (curr_row['low'] <= curr_row['ma50'] <= curr_row['high'])
                )
                
                if not is_ma50_touch:
                    continue
                
                # 조건 2: 이후 양봉 캔들 출현 확인 (다음 1-3개 캔들 중)
                bullish_found = False
                bullish_index = -1
                
                for k in range(1, min(4, len(recent_df) - j)):
                    next_candle = recent_df.iloc[j + k]
                    if next_candle['close'] > next_candle['open']:  # 양봉
                        bullish_found = True
                        bullish_index = j + k
                        break
                
                if not bullish_found:
                    continue
                
                # 조건 3: 200MA 터치 후 상승 확인 (양봉 이후 캔들들에서)
                ma200_touch_and_rise = False
                ma200_touch_index = -1
                
                for k in range(bullish_index + 1, min(bullish_index + 5, len(recent_df))):
                    check_candle = recent_df.iloc[k]
                    
                    if pd.isna(check_candle['ma200']):
                        continue
                    
                    # 200MA 터치 확인
                    ma200_touch_threshold = check_candle['ma200'] * 0.015  # 1.5% 오차 허용
                    is_ma200_touch = (
                        abs(check_candle['low'] - check_candle['ma200']) <= ma200_touch_threshold or
                        (check_candle['low'] <= check_candle['ma200'] <= check_candle['high'])
                    )
                    
                    if is_ma200_touch:
                        # 터치 후 상승 확인 (다음 캔들이 200MA 위에서 마감)
                        if k + 1 < len(recent_df):
                            next_candle = recent_df.iloc[k + 1]
                            if next_candle['close'] > check_candle['ma200']:
                                ma200_touch_and_rise = True
                                ma200_touch_index = k
                                break
                
                if not ma200_touch_and_rise:
                    continue
                
                # 조건 4: 거래량 증가 확인
                volume_surge = False
                if j >= 10:  # 충분한 과거 데이터가 있을 때
                    # 50MA 터치 이전 10개 캔들의 평균 거래량
                    prev_volumes = [recent_df.iloc[j - k]['volume'] for k in range(1, 11)]
                    avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
                    
                    # 신호 발생 시점의 거래량 (200MA 터치 후 상승 시점)
                    signal_volume = recent_df.iloc[ma200_touch_index]['volume']
                    
                    # 거래량이 평균의 1.3배 이상이면 증가로 판단
                    if signal_volume > avg_prev_volume * 1.3:
                        volume_surge = True
                
                if not volume_surge:
                    continue
                
                # 모든 조건을 만족하는 신호 발견!
                signal_candle = recent_df.iloc[ma200_touch_index]
                days_ago = (datetime.now() - signal_candle['timestamp'].to_pydatetime()).days
                
                # 현재가 조회
                current_price = get_current_price(symbol)
                if current_price is None:
                    current_price = recent_df.iloc[-1]['close']
                
                # 신호 이후 수익률 계산
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
                # 가장 최근 신호만 저장
                latest_signal = pre_signals[-1]
                pre_signal_results.append(latest_signal)
                print(f"   ✅ {coin_name}: {latest_signal['days_ago']}일 전 선행신호 ({latest_signal['profit_rate']:+.1f}%)")
            else:
                print(f"   ❌ {coin_name}: 1달 이내 선행신호 없음")
        
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            continue
        
        # API 요청 제한 방지
        time.sleep(0.1)
    
    # 결과 출력
    if pre_signal_results:
        print(f"\n🎯 골든크로스 이전 선행신호 발견: {len(pre_signal_results)}개")
        print("=" * 150)
        
        # 수익률 기준으로 정렬
        pre_signal_results.sort(key=lambda x: x['profit_rate'], reverse=True)
        
        print(f"{'순위':<4} {'종목':<10} {'신호일자':<12} {'경과일':<6} {'신호가격':<12} {'현재가격':<12} {'수익률':<8} {'거래량비율':<8} {'MA상태':<25}")
        print("-" * 150)
        
        for i, signal in enumerate(pre_signal_results):
            rank = i + 1
            coin_name = signal['coin_name']
            signal_date = signal['signal_date'].strftime('%m-%d %H:%M')
            days_ago = f"{signal['days_ago']}일전"
            signal_price = f"{signal['signal_price']:,.0f}"
            current_price = f"{signal['current_price']:,.0f}"
            profit_rate = f"{signal['profit_rate']:+.1f}%"
            volume_ratio = f"{signal['volume_ratio']:.1f}x"
            
            # MA 상태 표시
            ma_status = f"20:{signal['ma20']:.0f} 50:{signal['ma50']:.0f} 200:{signal['ma200']:.0f}"
            
            # 수익률에 따른 이모지
            if signal['profit_rate'] > 10:
                emoji = "🚀"
            elif signal['profit_rate'] > 5:
                emoji = "📈"
            elif signal['profit_rate'] > 0:
                emoji = "✅"
            elif signal['profit_rate'] > -5:
                emoji = "⚠️"
            else:
                emoji = "📉"
            
            print(f"{rank:<4} {emoji} {coin_name:<8} {signal_date:<12} {days_ago:<6} {signal_price:<12} {current_price:<12} {profit_rate:<8} {volume_ratio:<8} {ma_status:<25}")
        
        # 통계 요약
        positive_signals = [s for s in pre_signal_results if s['profit_rate'] > 0]
        avg_profit = sum(s['profit_rate'] for s in pre_signal_results) / len(pre_signal_results)
        max_profit = max(s['profit_rate'] for s in pre_signal_results)
        min_profit = min(s['profit_rate'] for s in pre_signal_results)
        
        print("\n" + "=" * 150)
        print(f"📊 선행신호 통계 요약:")
        print(f"   🎯 성공률: {len(positive_signals)}/{len(pre_signal_results)} ({len(positive_signals)/len(pre_signal_results)*100:.1f}%)")
        print(f"   📈 평균 수익률: {avg_profit:+.2f}%")
        print(f"   🚀 최고 수익률: {max_profit:+.2f}%")
        print(f"   📉 최저 수익률: {min_profit:+.2f}%")
        
        # 상위 3개 종목 상세 정보
        print(f"\n🏆 상위 3개 종목 상세 정보:")
        print("-" * 100)
        
        for i, signal in enumerate(pre_signal_results[:3]):
            print(f"\n{i+1}. 🌟 {signal['coin_name']}")
            print(f"   📅 50MA 터치: {signal['ma50_touch_date'].strftime('%Y-%m-%d %H:%M')}")
            print(f"   📈 양봉 출현: {signal['bullish_date'].strftime('%Y-%m-%d %H:%M')}")
            print(f"   🎯 200MA 터치 후 상승: {signal['signal_date'].strftime('%Y-%m-%d %H:%M')}")
            print(f"   💰 신호가격: {signal['signal_price']:,.0f} KRW → 현재가: {signal['current_price']:,.0f} KRW")
            print(f"   📊 수익률: {signal['profit_rate']:+.2f}%")
            print(f"   📈 거래량 증가: {signal['volume_ratio']:.1f}배")
    
    else:
        print("\n❌ 1달 이내 선행신호를 발견한 종목이 없습니다.")
        print("💡 조건을 완화하거나 분석 기간을 늘려보세요.")
    
    return pre_signal_results

def analyze_recent_pre_signals():
    """3일 이내 골든크로스 이전 선행신호 긴급 분석"""
    print(f"\n🚨 3일 이내 골든크로스 이전 선행신호 긴급 분석")
    print("📋 분석 목적: 골든크로스 임박 가능성이 높은 종목 발굴")
    print("⏰ 분석 기간: 최근 3일 (72시간)")
    print("🎯 주의: 이 신호들은 곧 골든크로스가 발생할 가능성이 높습니다!")
    
    # 모든 KRW 종목 가져오기
    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("❌ 업비트 종목을 가져올 수 없습니다.")
        return
    
    print(f"\n📊 총 {len(all_tickers)}개 종목의 3일 이내 선행신호 분석 중...")
    
    # 3일 전부터 현재까지 분석
    three_days_ago = datetime.now() - pd.Timedelta(days=3)
    print(f"📅 분석 기간: {three_days_ago.strftime('%Y-%m-%d %H:%M')} ~ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    recent_signals = []
    
    for i, symbol in enumerate(all_tickers):
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/{len(all_tickers)}) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (최근 데이터 중심)
            all_data = []
            limit_per_request = 200
            total_requests = 3  # 600개 데이터 (약 3개월치)
            
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
                    
                    time.sleep(0.03)  # 빠른 분석을 위해 딜레이 단축
                    
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
            
            # 이동평균 계산 (20MA, 50MA, 200MA)
            df['ma20'] = df['close'].rolling(window=20, center=False).mean()
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 3일 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= three_days_ago].copy()
            
            if len(recent_df) < 5:
                print(f"   ⚠️ {coin_name}: 3일 이내 데이터 부족")
                continue
            
            # 선행 신호 탐지 (동일한 로직)
            pre_signals = []
            
            for j in range(10, len(recent_df) - 2):  # 최소한의 전후 데이터 확보
                curr_row = recent_df.iloc[j]
                
                # 전제 조건: 아직 골든크로스 이전 (50MA < 200MA)
                if pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or pd.isna(curr_row['ma20']):
                    continue
                
                if curr_row['ma50'] >= curr_row['ma200']:  # 이미 골든크로스 상태면 제외
                    continue
                
                # 조건 1: 50MA 터치 확인
                ma50_touch_threshold = curr_row['ma50'] * 0.02
                is_ma50_touch = (
                    abs(curr_row['low'] - curr_row['ma50']) <= ma50_touch_threshold or
                    (curr_row['low'] <= curr_row['ma50'] <= curr_row['high'])
                )
                
                if not is_ma50_touch:
                    continue
                
                # 조건 2: 이후 양봉 캔들 출현 확인
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
                
                # 조건 3: 200MA 터치 후 상승 확인
                ma200_touch_and_rise = False
                ma200_touch_index = -1
                
                for k in range(bullish_index + 1, min(bullish_index + 4, len(recent_df))):
                    check_candle = recent_df.iloc[k]
                    
                    if pd.isna(check_candle['ma200']):
                        continue
                    
                    # 200MA 터치 확인
                    ma200_touch_threshold = check_candle['ma200'] * 0.015
                    is_ma200_touch = (
                        abs(check_candle['low'] - check_candle['ma200']) <= ma200_touch_threshold or
                        (check_candle['low'] <= check_candle['ma200'] <= check_candle['high'])
                    )
                    
                    if is_ma200_touch:
                        # 터치 후 상승 확인
                        if k + 1 < len(recent_df):
                            next_candle = recent_df.iloc[k + 1]
                            if next_candle['close'] > check_candle['ma200']:
                                ma200_touch_and_rise = True
                                ma200_touch_index = k
                                break
                
                if not ma200_touch_and_rise:
                    continue
                
                # 조건 4: 거래량 증가 확인
                volume_surge = False
                if j >= 10:
                    prev_volumes = [recent_df.iloc[j - k]['volume'] for k in range(1, 11)]
                    avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
                    signal_volume = recent_df.iloc[ma200_touch_index]['volume']
                    
                    if signal_volume > avg_prev_volume * 1.3:
                        volume_surge = True
                
                if not volume_surge:
                    continue
                
                # 모든 조건을 만족하는 신호 발견!
                signal_candle = recent_df.iloc[ma200_touch_index]
                hours_ago = (datetime.now() - signal_candle['timestamp'].to_pydatetime()).total_seconds() / 3600
                
                # 현재가 조회
                current_price = get_current_price(symbol)
                if current_price is None:
                    current_price = recent_df.iloc[-1]['close']
                
                # 골든크로스 임박도 계산 (50MA와 200MA 간격)
                latest_data = recent_df.iloc[-1]
                ma_gap = abs(latest_data['ma50'] - latest_data['ma200'])
                ma_gap_percent = (ma_gap / latest_data['ma200']) * 100
                
                # 골든크로스 임박도 판단
                if ma_gap_percent < 1:
                    urgency = "🔥 매우 임박"
                elif ma_gap_percent < 2:
                    urgency = "⚡ 임박"
                elif ma_gap_percent < 3:
                    urgency = "🎯 근접"
                else:
                    urgency = "📊 관찰"
                
                pre_signals.append({
                    'symbol': symbol,
                    'coin_name': coin_name,
                    'signal_date': signal_candle['timestamp'],
                    'hours_ago': hours_ago,
                    'signal_price': signal_candle['close'],
                    'current_price': current_price,
                    'ma_gap_percent': ma_gap_percent,
                    'urgency': urgency,
                    'volume_ratio': signal_volume / avg_prev_volume,
                    'ma50': latest_data['ma50'],
                    'ma200': latest_data['ma200'],
                    'ma50_touch_date': curr_row['timestamp'],
                    'bullish_date': recent_df.iloc[bullish_index]['timestamp']
                })
            
            if pre_signals:
                # 가장 최근 신호만 저장
                latest_signal = pre_signals[-1]
                recent_signals.append(latest_signal)
                print(f"   🚨 {coin_name}: {latest_signal['hours_ago']:.1f}시간 전 선행신호 ({latest_signal['urgency']})")
            else:
                print(f"   ❌ {coin_name}: 3일 이내 선행신호 없음")
        
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            continue
        
        # API 요청 제한 방지
        time.sleep(0.05)
    
    # 결과 출력
    if recent_signals:
        print(f"\n🚨 3일 이내 골든크로스 이전 선행신호 발견: {len(recent_signals)}개")
        print("⚠️ 주의: 이 종목들은 곧 골든크로스가 발생할 가능성이 높습니다!")
        print("=" * 160)
        
        # 골든크로스 임박도 순으로 정렬
        recent_signals.sort(key=lambda x: x['ma_gap_percent'])
        
        print(f"{'순위':<4} {'종목':<8} {'신호시점':<16} {'경과시간':<10} {'골든크로스 임박도':<12} {'현재 MA 간격':<10} {'거래량':<8} {'신호가격':<10} {'현재가격':<10}")
        print("-" * 160)
        
        for i, signal in enumerate(recent_signals):
            rank = i + 1
            coin_name = signal['coin_name']
            signal_time = signal['signal_date'].strftime('%m-%d %H:%M')
            hours_ago = f"{signal['hours_ago']:.1f}h"
            urgency = signal['urgency']
            ma_gap = f"{signal['ma_gap_percent']:.2f}%"
            volume_ratio = f"{signal['volume_ratio']:.1f}x"
            signal_price = f"{signal['signal_price']:,.0f}"
            current_price = f"{signal['current_price']:,.0f}"
            
            print(f"{rank:<4} {coin_name:<8} {signal_time:<16} {hours_ago:<10} {urgency:<12} {ma_gap:<10} {volume_ratio:<8} {signal_price:<10} {current_price:<10}")
        
        # 긴급도별 분류
        urgent_signals = [s for s in recent_signals if "매우 임박" in s['urgency'] or "임박" in s['urgency']]
        
        if urgent_signals:
            print(f"\n🔥 골든크로스 매우 임박 종목 ({len(urgent_signals)}개)")
            print("=" * 120)
            print("⚠️ 이 종목들은 24-48시간 내 골든크로스 발생 가능성이 매우 높습니다!")
            print("-" * 120)
            
            for signal in urgent_signals:
                profit_potential = ((signal['current_price'] - signal['signal_price']) / signal['signal_price']) * 100
                print(f"🚨 {signal['coin_name']}")
                print(f"   📅 선행신호: {signal['signal_date'].strftime('%Y-%m-%d %H:%M')} ({signal['hours_ago']:.1f}시간 전)")
                print(f"   🎯 임박도: {signal['urgency']} (MA 간격: {signal['ma_gap_percent']:.2f}%)")
                print(f"   💰 가격: {signal['signal_price']:,.0f} → {signal['current_price']:,.0f} KRW")
                print(f"   📊 현재 수익률: {profit_potential:+.2f}%")
                print(f"   📈 거래량: {signal['volume_ratio']:.1f}배 증가")
                print(f"   📊 MA50: {signal['ma50']:,.0f} | MA200: {signal['ma200']:,.0f}")
                print()
        
        # 통계 요약
        avg_gap = sum(s['ma_gap_percent'] for s in recent_signals) / len(recent_signals)
        very_urgent = len([s for s in recent_signals if "매우 임박" in s['urgency']])
        urgent = len([s for s in recent_signals if "임박" in s['urgency']])
        near = len([s for s in recent_signals if "근접" in s['urgency']])
        
        print(f"\n📊 3일 이내 선행신호 통계:")
        print(f"   🔥 매우 임박 (1% 미만): {very_urgent}개")
        print(f"   ⚡ 임박 (1-2%): {urgent}개") 
        print(f"   🎯 근접 (2-3%): {near}개")
        print(f"   📊 관찰 (3% 이상): {len(recent_signals) - very_urgent - urgent - near}개")
        print(f"   📈 평균 MA 간격: {avg_gap:.2f}%")
        
        print(f"\n💡 투자 전략 가이드:")
        print(f"   🔥 매우 임박: 즉시 모니터링, 골든크로스 발생 시 진입 준비")
        print(f"   ⚡ 임박: 24-48시간 내 골든크로스 가능성 높음")
        print(f"   🎯 근접: 1주일 내 골든크로스 가능성")
        print(f"   📊 관찰: 지속적인 모니터링 필요")
    
    else:
        print("\n❌ 3일 이내 골든크로스 이전 선행신호를 발견한 종목이 없습니다.")
        print("💡 시장이 안정적이거나 대부분 종목이 이미 골든크로스를 지났을 수 있습니다.")
    
    return recent_signals

def analyze_high_profit_patterns():
    """골든크로스 직전 선행신호 중 수익률 높은 종목들의 차트 지표 공통점 분석"""
    print(f"\n📊 골든크로스 직전 선행신호 고수익 종목 패턴 분석")
    print("🎯 분석 목적: 수익률 높은 종목들의 차트 지표 공통점 발굴")
    print("📋 분석 대상: 1달 이내 선행신호 발생 후 수익률 상위 종목")
    
    # 먼저 1달 이내 선행신호 분석 실행
    print("\n🔍 1단계: 선행신호 종목 수집 중...")
    pre_signals = analyze_pre_golden_cross_signals()
    
    if not pre_signals or len(pre_signals) < 5:
        print("❌ 분석할 충분한 선행신호 종목이 없습니다. (최소 5개 필요)")
        return
    
    # 수익률 기준으로 정렬하고 상위 30% 선택
    pre_signals.sort(key=lambda x: ((x['current_price'] - x['signal_price']) / x['signal_price']) * 100, reverse=True)
    
    # 수익률 계산
    for signal in pre_signals:
        signal['profit_rate'] = ((signal['current_price'] - signal['signal_price']) / signal['signal_price']) * 100
    
    # 상위 30% 종목 선택 (최소 3개, 최대 20개)
    top_count = max(3, min(20, int(len(pre_signals) * 0.3)))
    high_profit_signals = pre_signals[:top_count]
    
    print(f"\n📈 2단계: 상위 {top_count}개 고수익 종목 상세 분석")
    print("=" * 120)
    
    # 고수익 종목 리스트 출력
    print(f"{'순위':<4} {'종목':<8} {'수익률':<10} {'신호가격':<12} {'현재가격':<12} {'거래량비율':<10}")
    print("-" * 120)
    
    for i, signal in enumerate(high_profit_signals):
        rank = i + 1
        coin_name = signal['coin_name']
        profit_rate = f"{signal['profit_rate']:+.1f}%"
        signal_price = f"{signal['signal_price']:,.0f}"
        current_price = f"{signal['current_price']:,.0f}"
        volume_ratio = f"{signal['volume_ratio']:.1f}x"
        
        print(f"{rank:<4} {coin_name:<8} {profit_rate:<10} {signal_price:<12} {current_price:<12} {volume_ratio:<10}")
    
    print("\n🔍 3단계: 차트 지표 상세 분석 중...")
    
    # 각 고수익 종목의 상세 차트 지표 분석
    detailed_analysis = []
    
    for i, signal in enumerate(high_profit_signals):
        symbol = signal['symbol']
        coin_name = signal['coin_name']
        
        print(f"📊 분석 중... ({i+1}/{len(high_profit_signals)}) {coin_name}")
        
        try:
            # 충분한 데이터 수집 (신호 발생 전후 분석을 위해)
            all_data = []
            limit_per_request = 200
            total_requests = 8  # 1600개 데이터 (약 10개월치)
            
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
                print(f"   ⚠️ {coin_name}: 데이터 부족")
                continue
            
            # 데이터프레임 생성
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            df = df.dropna(subset=['close'])
            df = df[df['close'] > 0].reset_index(drop=True)
            
            # 다양한 기술적 지표 계산
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma10'] = df['close'].rolling(window=10).mean()
            df['ma20'] = df['close'].rolling(window=20).mean()
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
            ema12 = df['close'].ewm(span=12).mean()
            ema26 = df['close'].ewm(span=26).mean()
            df['macd'] = ema12 - ema26
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            
            # 거래량 지표
            df['volume_ma20'] = df['volume'].rolling(window=20).mean()
            df['volume_ratio'] = df['volume'] / df['volume_ma20']
            
            # 캔들 패턴 분석
            df['body_size'] = abs(df['close'] - df['open']) / df['open'] * 100
            df['upper_shadow'] = (df['high'] - df[['close', 'open']].max(axis=1)) / df['open'] * 100
            df['lower_shadow'] = (df[['close', 'open']].min(axis=1) - df['low']) / df['open'] * 100
            df['is_bullish'] = df['close'] > df['open']
            
            # 신호 발생 시점 찾기
            signal_date = signal['signal_date']
            signal_idx = None
            
            for idx, row in df.iterrows():
                if abs((row['timestamp'] - signal_date).total_seconds()) < 7200:  # 2시간 오차 허용
                    signal_idx = idx
                    break
            
            if signal_idx is None or signal_idx < 50:
                print(f"   ⚠️ {coin_name}: 신호 시점 찾기 실패")
                continue
            
            # 신호 발생 시점의 지표 값들 수집
            signal_row = df.iloc[signal_idx]
            
            # 신호 발생 전 10개 캔들 평균값 계산
            pre_signal_df = df.iloc[signal_idx-10:signal_idx]
            
            analysis_data = {
                'coin_name': coin_name,
                'profit_rate': signal['profit_rate'],
                'signal_date': signal_date,
                
                # 신호 시점 지표
                'rsi_signal': signal_row['rsi'],
                'bb_position_signal': signal_row['bb_position'],
                'macd_signal': signal_row['macd'],
                'macd_histogram_signal': signal_row['macd_histogram'],
                'volume_ratio_signal': signal_row['volume_ratio'],
                
                # MA 관계
                'ma5_vs_ma10': (signal_row['ma5'] - signal_row['ma10']) / signal_row['ma10'] * 100,
                'ma10_vs_ma20': (signal_row['ma10'] - signal_row['ma20']) / signal_row['ma20'] * 100,
                'ma20_vs_ma50': (signal_row['ma20'] - signal_row['ma50']) / signal_row['ma50'] * 100,
                'ma50_vs_ma200': (signal_row['ma50'] - signal_row['ma200']) / signal_row['ma200'] * 100,
                
                # 캔들 패턴 (신호 전 10개 캔들 평균)
                'avg_body_size': pre_signal_df['body_size'].mean(),
                'avg_upper_shadow': pre_signal_df['upper_shadow'].mean(),
                'avg_lower_shadow': pre_signal_df['lower_shadow'].mean(),
                'bullish_ratio': pre_signal_df['is_bullish'].sum() / len(pre_signal_df),
                
                # 거래량 패턴
                'avg_volume_ratio': pre_signal_df['volume_ratio'].mean(),
                'volume_trend': (pre_signal_df['volume_ratio'].iloc[-3:].mean() - 
                               pre_signal_df['volume_ratio'].iloc[:3].mean()),
                
                # 가격 변동성
                'price_volatility': pre_signal_df['close'].std() / pre_signal_df['close'].mean() * 100,
            }
            
            detailed_analysis.append(analysis_data)
            
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            continue
        
        time.sleep(0.05)
    
    if not detailed_analysis:
        print("❌ 상세 분석할 데이터가 없습니다.")
        return
    
    # 공통점 분석
    print(f"\n📊 4단계: 고수익 종목들의 공통 패턴 분석")
    print("=" * 120)
    
    # 각 지표별 평균값 계산
    indicators = [
        'rsi_signal', 'bb_position_signal', 'macd_signal', 'macd_histogram_signal',
        'volume_ratio_signal', 'ma5_vs_ma10', 'ma10_vs_ma20', 'ma20_vs_ma50', 'ma50_vs_ma200',
        'avg_body_size', 'avg_upper_shadow', 'avg_lower_shadow', 'bullish_ratio',
        'avg_volume_ratio', 'volume_trend', 'price_volatility'
    ]
    
    pattern_summary = {}
    for indicator in indicators:
        values = [data[indicator] for data in detailed_analysis if not pd.isna(data[indicator])]
        if values:
            pattern_summary[indicator] = {
                'mean': sum(values) / len(values),
                'min': min(values),
                'max': max(values),
                'count': len(values)
            }
    
    # 결과 출력
    print(f"\n🎯 고수익 종목들의 공통 패턴 ({len(detailed_analysis)}개 종목 분석)")
    print("-" * 120)
    
    print(f"\n📈 1. 기술적 지표 공통점:")
    if 'rsi_signal' in pattern_summary:
        rsi_avg = pattern_summary['rsi_signal']['mean']
        print(f"   RSI: 평균 {rsi_avg:.1f} ({'과매수' if rsi_avg > 70 else '과매도' if rsi_avg < 30 else '중립'})")
    
    if 'bb_position_signal' in pattern_summary:
        bb_avg = pattern_summary['bb_position_signal']['mean']
        bb_desc = "상단 근처" if bb_avg > 0.8 else "하단 근처" if bb_avg < 0.2 else "중간 영역"
        print(f"   볼린저밴드 위치: 평균 {bb_avg:.2f} ({bb_desc})")
    
    if 'macd_histogram_signal' in pattern_summary:
        macd_hist_avg = pattern_summary['macd_histogram_signal']['mean']
        print(f"   MACD 히스토그램: 평균 {macd_hist_avg:.4f} ({'상승 모멘텀' if macd_hist_avg > 0 else '하락 모멘텀'})")
    
    print(f"\n📊 2. 이동평균 관계:")
    ma_relationships = ['ma5_vs_ma10', 'ma10_vs_ma20', 'ma20_vs_ma50', 'ma50_vs_ma200']
    ma_names = ['MA5 vs MA10', 'MA10 vs MA20', 'MA20 vs MA50', 'MA50 vs MA200']
    
    for ma_rel, ma_name in zip(ma_relationships, ma_names):
        if ma_rel in pattern_summary:
            ma_avg = pattern_summary[ma_rel]['mean']
            trend = "상승 배열" if ma_avg > 0 else "하락 배열"
            print(f"   {ma_name}: 평균 {ma_avg:+.2f}% ({trend})")
    
    print(f"\n🕯️ 3. 캔들 패턴 특징:")
    if 'avg_body_size' in pattern_summary:
        body_avg = pattern_summary['avg_body_size']['mean']
        print(f"   평균 몸통 크기: {body_avg:.2f}% ({'강한 캔들' if body_avg > 3 else '약한 캔들'})")
    
    if 'bullish_ratio' in pattern_summary:
        bullish_avg = pattern_summary['bullish_ratio']['mean']
        print(f"   양봉 비율: {bullish_avg:.1%} ({'강세 우세' if bullish_avg > 0.6 else '약세 우세' if bullish_avg < 0.4 else '균형'})")
    
    if 'avg_upper_shadow' in pattern_summary:
        upper_shadow_avg = pattern_summary['avg_upper_shadow']['mean']
        print(f"   평균 위꼬리: {upper_shadow_avg:.2f}%")
    
    if 'avg_lower_shadow' in pattern_summary:
        lower_shadow_avg = pattern_summary['avg_lower_shadow']['mean']
        print(f"   평균 아래꼬리: {lower_shadow_avg:.2f}%")
    
    print(f"\n📈 4. 거래량 패턴:")
    if 'volume_ratio_signal' in pattern_summary:
        vol_ratio_avg = pattern_summary['volume_ratio_signal']['mean']
        print(f"   신호시점 거래량 비율: {vol_ratio_avg:.1f}배 ({'거래량 급증' if vol_ratio_avg > 2 else '보통'})")
    
    if 'volume_trend' in pattern_summary:
        vol_trend_avg = pattern_summary['volume_trend']['mean']
        trend_desc = "증가 추세" if vol_trend_avg > 0.1 else "감소 추세" if vol_trend_avg < -0.1 else "횡보"
        print(f"   거래량 추세: {vol_trend_avg:+.2f} ({trend_desc})")
    
    print(f"\n⚡ 5. 변동성 특징:")
    if 'price_volatility' in pattern_summary:
        volatility_avg = pattern_summary['price_volatility']['mean']
        vol_desc = "고변동성" if volatility_avg > 5 else "저변동성" if volatility_avg < 2 else "중간변동성"
        print(f"   가격 변동성: {volatility_avg:.2f}% ({vol_desc})")
    
    # 핵심 패턴 요약
    print(f"\n🎯 핵심 성공 패턴 요약:")
    print("=" * 80)
    
    success_patterns = []
    
    # RSI 패턴
    if 'rsi_signal' in pattern_summary:
        rsi_avg = pattern_summary['rsi_signal']['mean']
        if 30 <= rsi_avg <= 70:
            success_patterns.append(f"✅ RSI {rsi_avg:.0f} 중립권에서 신호 발생")
        elif rsi_avg < 30:
            success_patterns.append(f"✅ RSI {rsi_avg:.0f} 과매도 구간에서 반등 신호")
    
    # 볼린저밴드 패턴
    if 'bb_position_signal' in pattern_summary:
        bb_avg = pattern_summary['bb_position_signal']['mean']
        if bb_avg < 0.3:
            success_patterns.append(f"✅ 볼린저밴드 하단 근처에서 반등")
        elif 0.3 <= bb_avg <= 0.7:
            success_patterns.append(f"✅ 볼린저밴드 중간 영역에서 상승 돌입")
    
    # MA 배열 패턴
    if 'ma50_vs_ma200' in pattern_summary:
        ma_gap = pattern_summary['ma50_vs_ma200']['mean']
        if -5 <= ma_gap <= 0:
            success_patterns.append(f"✅ 골든크로스 직전 상태 (MA50이 MA200 {abs(ma_gap):.1f}% 아래)")
    
    # 거래량 패턴
    if 'volume_ratio_signal' in pattern_summary:
        vol_ratio = pattern_summary['volume_ratio_signal']['mean']
        if vol_ratio > 1.5:
            success_patterns.append(f"✅ 평균 {vol_ratio:.1f}배 거래량 증가 동반")
    
    # 캔들 패턴
    if 'bullish_ratio' in pattern_summary:
        bullish_ratio = pattern_summary['bullish_ratio']['mean']
        if bullish_ratio > 0.6:
            success_patterns.append(f"✅ 신호 전 {bullish_ratio:.0%} 양봉 우세")
    
    for i, pattern in enumerate(success_patterns, 1):
        print(f"{i}. {pattern}")
    
    # 투자 가이드라인
    print(f"\n💡 투자 가이드라인:")
    print("-" * 80)
    print("🎯 진입 조건:")
    print("   • RSI 30-70 구간에서 신호 발생")
    print("   • 볼린저밴드 하단~중간 영역")
    print("   • MA50이 MA200에 근접 (골든크로스 임박)")
    print("   • 거래량 1.5배 이상 증가")
    print("   • 최근 양봉 캔들 우세")
    
    print(f"\n⚠️ 주의사항:")
    print("   • 모든 조건을 동시에 만족하는 종목 우선 선택")
    print("   • 거래량 없는 신호는 피할 것")
    print("   • 과매수 구간(RSI 70 이상)에서는 신중 접근")
    
    # 개별 종목 상세 분석 결과
    print(f"\n📋 개별 종목 상세 분석:")
    print("=" * 150)
    print(f"{'종목':<8} {'수익률':<8} {'RSI':<6} {'BB위치':<8} {'MACD':<8} {'거래량':<8} {'양봉비율':<8} {'변동성':<8}")
    print("-" * 150)
    
    for data in detailed_analysis:
        coin_name = data['coin_name']
        profit_rate = f"{data['profit_rate']:+.1f}%"
        rsi = f"{data.get('rsi_signal', 0):.0f}" if not pd.isna(data.get('rsi_signal', float('nan'))) else "N/A"
        bb_pos = f"{data.get('bb_position_signal', 0):.2f}" if not pd.isna(data.get('bb_position_signal', float('nan'))) else "N/A"
        macd = f"{data.get('macd_histogram_signal', 0):+.3f}" if not pd.isna(data.get('macd_histogram_signal', float('nan'))) else "N/A"
        volume = f"{data.get('volume_ratio_signal', 0):.1f}x" if not pd.isna(data.get('volume_ratio_signal', float('nan'))) else "N/A"
        bullish = f"{data.get('bullish_ratio', 0):.0%}" if not pd.isna(data.get('bullish_ratio', float('nan'))) else "N/A"
        volatility = f"{data.get('price_volatility', 0):.1f}%" if not pd.isna(data.get('price_volatility', float('nan'))) else "N/A"
        
        print(f"{coin_name:<8} {profit_rate:<8} {rsi:<6} {bb_pos:<8} {macd:<8} {volume:<8} {bullish:<8} {volatility:<8}")
    
    return detailed_analysis

def analyze_pattern_matching():
    """1번 선행신호 분석 기반 일주일 내 최고 수익률 종목 패턴 추출"""
    print(f"\n🎯 선행신호 기반 고수익 종목 패턴 분석")
    print("📋 분석 목적: 1번 선행신호 분석 종목들 중 일주일 내 최고 수익률을 기록한 종목들의 공통 패턴 추출")
    print("🔍 분석 과정:")
    print("   1. 1번 선행신호 분석 실행")
    print("   2. 각 종목의 선행신호 발생 후 일주일 내 최고 수익률 계산")
    print("   3. 고수익 종목들의 공통 패턴 추출")
    print("   4. 패턴 기반 투자 가이드라인 제시")
    
    # 1단계: 1번 선행신호 분석 실행
    print("\n🔍 1단계: 선행신호 분석 실행 중...")
    
    # 모든 KRW 종목 가져오기
    all_tickers = get_krw_tickers()
    
    if not all_tickers:
        print("❌ 업비트 종목을 가져올 수 없습니다.")
        return
    
    print(f"\n📊 총 {len(all_tickers)}개 종목의 선행 신호 분석 중...")
    
    # 1달 전부터 현재까지 분석
    one_month_ago = datetime.now() - pd.Timedelta(days=30)
    print(f"📅 분석 기간: {one_month_ago.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}")
    
    pre_signal_results = []
    
    for i, symbol in enumerate(all_tickers[:20]):  # 처리 시간을 위해 상위 20개만 분석
        coin_name = symbol.replace('KRW/', '').replace('/KRW', '')
        
        print(f"🔍 분석 중... ({i+1}/20) {coin_name}")
        
        try:
            # 4시간 데이터 조회 (충분한 데이터 확보)
            all_data = []
            limit_per_request = 200
            total_requests = 6  # 1200개 데이터 (약 8개월치)
            
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
            
            if len(df) < 300:
                print(f"   ⚠️ {coin_name}: 정제 후 데이터 부족")
                continue
            
            # 이동평균 계산 (20MA, 50MA, 200MA)
            df['ma20'] = df['close'].rolling(window=20, center=False).mean()
            df['ma50'] = df['close'].rolling(window=50, center=False).mean()
            df['ma200'] = df['close'].rolling(window=200, center=False).mean()
            
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
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            
            # MA200이 유효한 데이터부터만 사용
            ma200_first_valid = df['ma200'].first_valid_index()
            if ma200_first_valid is None:
                print(f"   ⚠️ {coin_name}: MA200 계산 불가")
                continue
            
            df_valid = df.iloc[ma200_first_valid:].copy().reset_index(drop=True)
            
            # 1달 이내 데이터만 필터링
            recent_df = df_valid[df_valid['timestamp'] >= one_month_ago].copy()
            
            if len(recent_df) < 20:
                print(f"   ⚠️ {coin_name}: 1달 이내 데이터 부족")
                continue
            
            # 선행 신호 탐지 (1번 분석과 동일한 로직)
            pre_signals = []
            
            for j in range(10, len(recent_df) - 10):  # 충분한 전후 데이터 확보
                curr_row = recent_df.iloc[j]
                
                # 전제 조건: 아직 골든크로스 이전 (50MA < 200MA)
                if pd.isna(curr_row['ma50']) or pd.isna(curr_row['ma200']) or pd.isna(curr_row['ma20']):
                    continue
                
                if curr_row['ma50'] >= curr_row['ma200']:  # 이미 골든크로스 상태면 제외
                    continue
                
                # 조건 1: 50MA 터치 확인
                ma50_touch_threshold = curr_row['ma50'] * 0.02  # 2% 오차 허용
                is_ma50_touch = (
                    abs(curr_row['low'] - curr_row['ma50']) <= ma50_touch_threshold or
                    (curr_row['low'] <= curr_row['ma50'] <= curr_row['high'])
                )
                
                if not is_ma50_touch:
                    continue
                
                # 조건 2: 이후 양봉 캔들 출현 확인
                bullish_found = False
                bullish_index = -1
                
                for k in range(1, min(4, len(recent_df) - j)):
                    next_candle = recent_df.iloc[j + k]
                    if next_candle['close'] > next_candle['open']:  # 양봉
                        bullish_found = True
                        bullish_index = j + k
                        break
                
                if not bullish_found:
                    continue
                
                # 조건 3: 200MA 터치 후 상승 확인
                ma200_touch_and_rise = False
                ma200_touch_index = -1
                
                for k in range(bullish_index + 1, min(bullish_index + 5, len(recent_df))):
                    check_candle = recent_df.iloc[k]
                    
                    if pd.isna(check_candle['ma200']):
                        continue
                    
                    # 200MA 터치 확인
                    ma200_touch_threshold = check_candle['ma200'] * 0.015  # 1.5% 오차 허용
                    is_ma200_touch = (
                        abs(check_candle['low'] - check_candle['ma200']) <= ma200_touch_threshold or
                        (check_candle['low'] <= check_candle['ma200'] <= check_candle['high'])
                    )
                    
                    if is_ma200_touch:
                        # 터치 후 상승 확인
                        if k + 1 < len(recent_df):
                            next_candle = recent_df.iloc[k + 1]
                            if next_candle['close'] > check_candle['ma200']:
                                ma200_touch_and_rise = True
                                ma200_touch_index = k
                                break
                
                if not ma200_touch_and_rise:
                    continue
                
                # 조건 4: 거래량 증가 확인
                volume_surge = False
                if j >= 10:
                    prev_volumes = [recent_df.iloc[j - k]['volume'] for k in range(1, 11)]
                    avg_prev_volume = sum(prev_volumes) / len(prev_volumes)
                    
                    signal_volume = recent_df.iloc[ma200_touch_index]['volume']
                    if signal_volume > avg_prev_volume * 1.3:  # 1.3배 이상
                        volume_surge = True
                
                if not volume_surge:
                    continue
                
                # 선행신호 발생 시점 기록
                signal_date = recent_df.iloc[ma200_touch_index]['timestamp']
                signal_price = recent_df.iloc[ma200_touch_index]['close']
                signal_row = recent_df.iloc[ma200_touch_index]
                
                # 일주일 후 최고가 계산
                one_week_later = signal_date + pd.Timedelta(days=7)
                week_data = recent_df[
                    (recent_df['timestamp'] > signal_date) & 
                    (recent_df['timestamp'] <= one_week_later)
                ]
                
                if len(week_data) > 0:
                    max_price_in_week = week_data['high'].max()
                    max_profit_rate = ((max_price_in_week - signal_price) / signal_price) * 100
                    
                    # 현재가 대비 수익률도 계산
                    current_price = recent_df.iloc[-1]['close']
                    current_profit_rate = ((current_price - signal_price) / signal_price) * 100
                    
                    pre_signals.append({
                        'coin_name': coin_name,
                        'symbol': symbol,
                        'signal_date': signal_date,
                        'signal_price': signal_price,
                        'max_price_in_week': max_price_in_week,
                        'max_profit_rate': max_profit_rate,
                        'current_price': current_price,
                        'current_profit_rate': current_profit_rate,
                        'rsi': signal_row['rsi'],
                        'bb_position': signal_row['bb_position'],
                        'macd': signal_row['macd'],
                        'macd_signal': signal_row['macd_signal'],
                        'volume_ratio': signal_row['volume'] / recent_df.iloc[j-10:j]['volume'].mean(),
                        'ma50_distance': abs(signal_row['ma50'] - signal_row['ma200']) / signal_row['ma200'] * 100
                    })
                    
                    print(f"   ✅ {coin_name}: 선행신호 발견 - 일주일 최고 수익률 {max_profit_rate:.1f}%")
            
            if pre_signals:
                pre_signal_results.extend(pre_signals)
            else:
                print(f"   ❌ {coin_name}: 선행신호 없음")
                
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
            continue
        
        time.sleep(0.05)
    
    if not pre_signal_results:
        print("❌ 선행신호를 발견한 종목이 없습니다.")
        return
    
    # 2단계: 일주일 내 최고 수익률 기준으로 정렬
    print(f"\n📊 2단계: {len(pre_signal_results)}개 선행신호 종목의 일주일 내 수익률 분석")
    print("=" * 150)
    
    # 수익률 기준으로 내림차순 정렬
    pre_signal_results.sort(key=lambda x: x['max_profit_rate'], reverse=True)
    
    # 상위 수익률 종목들 출력
    print(f"{'순위':<4} {'종목':<8} {'신호일':<12} {'신호가격':<12} {'일주일최고가':<15} {'최고수익률':<12} {'현재수익률':<12}")
    print("-" * 150)
    
    for i, signal in enumerate(pre_signal_results):
        rank = i + 1
        coin_name = signal['coin_name']
        signal_date = signal['signal_date'].strftime('%m-%d')
        signal_price = f"{signal['signal_price']:,.0f}원"
        max_price = f"{signal['max_price_in_week']:,.0f}원"
        max_profit = f"{signal['max_profit_rate']:+.1f}%"
        current_profit = f"{signal['current_profit_rate']:+.1f}%"
        
        print(f"{rank:<4} {coin_name:<8} {signal_date:<12} {signal_price:<12} {max_price:<15} {max_profit:<12} {current_profit:<12}")
    
    # 3단계: 고수익 종목들의 공통 패턴 추출
    print(f"\n🎯 3단계: 고수익 종목들의 공통 패턴 추출")
    print("=" * 120)
    
    # 상위 30% 종목을 고수익 그룹으로 분류
    top_30_percent_count = max(1, len(pre_signal_results) // 3)
    high_profit_signals = pre_signal_results[:top_30_percent_count]
    low_profit_signals = pre_signal_results[top_30_percent_count:]
    
    print(f"📈 고수익 그룹: 상위 {top_30_percent_count}개 종목 (평균 수익률: {sum(s['max_profit_rate'] for s in high_profit_signals) / len(high_profit_signals):.1f}%)")
    print(f"📉 일반 그룹: 나머지 {len(low_profit_signals)}개 종목 (평균 수익률: {sum(s['max_profit_rate'] for s in low_profit_signals) / len(low_profit_signals):.1f}%)")
    
    # 패턴 분석 함수
    def analyze_pattern_differences(high_group, low_group, pattern_name, value_key):
        if not high_group or not low_group:
            return
        
        # NaN 값 제거
        high_values = [s[value_key] for s in high_group if not pd.isna(s[value_key])]
        low_values = [s[value_key] for s in low_group if not pd.isna(s[value_key])]
        
        if not high_values or not low_values:
            return
        
        high_avg = sum(high_values) / len(high_values)
        low_avg = sum(low_values) / len(low_values)
        difference = high_avg - low_avg
        
        print(f"{pattern_name}: 고수익 {high_avg:.2f} vs 일반 {low_avg:.2f} (차이: {difference:+.2f})")
    
    print(f"\n🔍 기술적 지표 패턴 비교:")
    print("-" * 80)
    
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "RSI 평균값", "rsi")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "볼린저밴드 위치", "bb_position")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "MACD 값", "macd")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "거래량 비율", "volume_ratio")
    analyze_pattern_differences(high_profit_signals, low_profit_signals, "MA50-200 간격(%)", "ma50_distance")
    
    # 4단계: 성공 패턴 도출
    print(f"\n🌟 4단계: 고수익 종목 성공 패턴 도출")
    print("=" * 120)
    
    if high_profit_signals:
        # 고수익 그룹의 평균값 계산
        avg_rsi = sum(s['rsi'] for s in high_profit_signals if not pd.isna(s['rsi'])) / len([s for s in high_profit_signals if not pd.isna(s['rsi'])])
        avg_bb_pos = sum(s['bb_position'] for s in high_profit_signals if not pd.isna(s['bb_position'])) / len([s for s in high_profit_signals if not pd.isna(s['bb_position'])])
        avg_volume_ratio = sum(s['volume_ratio'] for s in high_profit_signals if not pd.isna(s['volume_ratio'])) / len([s for s in high_profit_signals if not pd.isna(s['volume_ratio'])])
        avg_ma_distance = sum(s['ma50_distance'] for s in high_profit_signals if not pd.isna(s['ma50_distance'])) / len([s for s in high_profit_signals if not pd.isna(s['ma50_distance'])])
        
        print(f"🎯 고수익 종목 핵심 패턴:")
        print(f"   📊 RSI: {avg_rsi:.1f} (중립권 유지)")
        print(f"   📈 볼린저밴드 위치: {avg_bb_pos:.2f} (0.5 = 중앙선)")
        print(f"   📊 거래량 비율: {avg_volume_ratio:.1f}배 (평균 대비)")
        print(f"   📏 MA50-200 간격: {avg_ma_distance:.1f}% (골든크로스 임박도)")
        
        # 투자 가이드라인
        print(f"\n💡 투자 가이드라인:")
        print("=" * 100)
        print("🚀 우선 투자 조건 (고수익 패턴):")
        print(f"   • RSI {avg_rsi-10:.0f}~{avg_rsi+10:.0f} 구간")
        print(f"   • 볼린저밴드 위치 {avg_bb_pos-0.2:.1f}~{avg_bb_pos+0.2:.1f}")
        print(f"   • 거래량 {avg_volume_ratio:.1f}배 이상 증가")
        print(f"   • MA50-200 간격 {avg_ma_distance:.1f}% 이내 (골든크로스 임박)")
        print("   • 50MA 터치 → 양봉 → 200MA 터치 후 상승 패턴")
        
        # 현재 추천 종목
        current_recommendations = []
        for signal in high_profit_signals:
            if signal['current_profit_rate'] > -5:  # 현재 손실이 5% 이내인 종목
                current_recommendations.append(signal)
        
        if current_recommendations:
            print(f"\n🌟 현재 추천 종목 ({len(current_recommendations)}개):")
            print("-" * 80)
            for signal in current_recommendations[:5]:  # 상위 5개만 표시
                coin_name = signal['coin_name']
                max_profit = signal['max_profit_rate']
                current_profit = signal['current_profit_rate']
                days_ago = (datetime.now() - signal['signal_date']).days
                
                print(f"   🚀 {coin_name}: 최고 {max_profit:+.1f}% 수익 기록, 현재 {current_profit:+.1f}% ({days_ago}일 전 신호)")
    
    return pre_signal_results

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
    
    return golden_cross_results

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
        print("=" * 70)
        print("📈 골든크로스 발생 후 3~4개의 양봉 캔들이 강하게 형성되면 진입 고려")
        print("📊 반드시 거래량 동반 상승일 때만 의미 있음")
        print("🚀 골든크로스 + 저항 돌파 + 거래량 증가 = 진짜 신호")
        print("⚠️ 반대로 거래량 없이 골든크로스만 발생 → 대부분 페이크")
        print("=" * 70)
        
        print("\n💡 분석 모드별 특징:")
        print("   1️⃣ 선행신호 분석 (1달): 골든크로스 이전 패턴으로 미리 포착")
        print("   2️⃣ 진입신호 분석 (2달): 골든크로스 발생 후 실제 진입 타이밍")
        print("   3️⃣ 긴급 분석 (3일): 골든크로스 임박 종목 실시간 모니터링")
        print("   4️⃣ 패턴 분석: 고수익 종목들의 차트 지표 공통점 발굴")
        print("   5️⃣ 부합도 분석: 핵심 성공 패턴 부합도와 수익률 상관관계 분석")
        print("   6️⃣ 전체 분석: 1번 + 2번 종합 분석")
        
        # 선택 메뉴
        print("\n📋 분석 메뉴:")
        print("1. 골든크로스 이전 선행신호 분석 - 1달 기준 (50MA터치→양봉→200MA터치후상승+거래량증가)")
        print("2. 골든크로스 발생 후 진입신호 분석 - 2달 기준")
        print("3. 🚨 3일 이내 골든크로스 이전 선행신호 긴급 분석 (골든크로스 임박 종목)")
        print("4. 📊 고수익 종목 패턴 분석 (차트 지표 공통점 발굴)")
        print("5. 🎯 선행신호 기반 고수익 종목 패턴 분석 (일주일 내 최고 수익률 종목 패턴 추출)")
        print("6. 전체 분석 (1번 + 2번)")
        
        choice = input("\n선택하세요 (1/2/3/4/5/6): ").strip()
        
        if choice == "1":
            # 골든크로스 이전 선행신호 분석 (1달 기준)
            analyze_pre_golden_cross_signals()
        elif choice == "2":
            # 업비트 전 종목의 골든크로스 분석 (2달 기준)
            analyze_all_coins_golden_cross()
        elif choice == "3":
            # 3일 이내 골든크로스 이전 선행신호 긴급 분석
            analyze_recent_pre_signals()
        elif choice == "4":
            # 고수익 종목 패턴 분석
            analyze_high_profit_patterns()
        elif choice == "5":
            # 선행신호 기반 고수익 종목 패턴 분석
            analyze_pattern_matching()
        elif choice == "6":
            # 전체 분석
            analyze_pre_golden_cross_signals()
            print("\n" + "="*80)
            analyze_all_coins_golden_cross()
        else:
            print("❌ 잘못된 선택입니다. 핵심 패턴 부합도 분석을 실행합니다.")
            analyze_pattern_matching()
        
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