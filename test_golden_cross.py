import ccxt
import pandas as pd
import time
from datetime import datetime

# 업비트 API 초기화
upbit = ccxt.upbit()

def get_ohlcv_simple(symbol, timeframe='4h'):
    try:
        data = upbit.fetch_ohlcv(symbol, timeframe=timeframe, limit=300)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"{symbol} 데이터 조회 실패: {e}")
        return None

def analyze_golden_cross_candidates():
    """3일 이내 골든크로스 예상 종목 분석"""
    print("🎯 3일 이내 골든크로스 예상 종목 분석")
    
    # 주요 종목들
    symbols = ['XRP/KRW', 'BTC/KRW', 'ETH/KRW', 'ADA/KRW', 'DOT/KRW']
    
    candidates = []
    
    for symbol in symbols:
        coin_name = symbol.replace('/KRW', '')
        print(f"🔍 분석 중... {coin_name}")
        
        try:
            df = get_ohlcv_simple(symbol)
            if df is None or len(df) < 250:
                print(f"   ❌ {coin_name}: 데이터 부족")
                continue
            
            # 이동평균 계산
            df['ma50'] = df['close'].rolling(window=50).mean()
            df['ma200'] = df['close'].rolling(window=200).mean()
            
            latest = df.iloc[-1]
            
            # MA 값 확인
            if pd.isna(latest['ma50']) or pd.isna(latest['ma200']):
                print(f"   ❌ {coin_name}: MA 계산 불가")
                continue
            
            # 데드크로스 상태 확인
            is_golden_cross = latest['ma50'] > latest['ma200']
            if is_golden_cross:
                print(f"   ❌ {coin_name}: 이미 골든크로스 상태")
                continue
            
            # MA 간격 계산
            ma_gap_percent = abs(latest['ma50'] - latest['ma200']) / latest['ma200'] * 100
            
            if ma_gap_percent <= 2.0:  # 2% 이내
                # 추세 확인
                recent_data = df.tail(12)
                ma50_trend = recent_data['ma50'].iloc[-1] > recent_data['ma50'].iloc[0]
                
                if ma50_trend:
                    candidates.append({
                        'coin_name': coin_name,
                        'current_price': latest['close'],
                        'ma_gap_percent': ma_gap_percent,
                        'ma50': latest['ma50'],
                        'ma200': latest['ma200']
                    })
                    print(f"   ✅ {coin_name}: 골든크로스 임박 - MA간격 {ma_gap_percent:.2f}%")
                else:
                    print(f"   ❌ {coin_name}: MA50 하락 추세")
            else:
                print(f"   ❌ {coin_name}: MA 간격 너무 큼 ({ma_gap_percent:.2f}%)")
        
        except Exception as e:
            print(f"   ❌ {coin_name}: 분석 실패 - {e}")
        
        time.sleep(0.5)  # API 제한 방지
    
    # 결과 출력
    print(f"\n📊 분석 결과")
    print("=" * 80)
    
    if candidates:
        print(f"🎯 {len(candidates)}개 골든크로스 임박 종목 발견")
        print(f"{'종목':<8} {'현재가':<15} {'MA간격':<10} {'MA50':<12} {'MA200':<12}")
        print("-" * 80)
        
        for candidate in sorted(candidates, key=lambda x: x['ma_gap_percent']):
            print(f"{candidate['coin_name']:<8} {candidate['current_price']:>12,.0f}원 {candidate['ma_gap_percent']:>7.2f}% {candidate['ma50']:>10,.0f} {candidate['ma200']:>10,.0f}")
    else:
        print("❌ 현재 3일 이내 골든크로스 예상 종목이 없습니다.")
    
    print("=" * 80)

if __name__ == "__main__":
    analyze_golden_cross_candidates()