import ccxt
import pandas as pd
import time
from datetime import datetime

# 업비트 API 초기화
upbit = ccxt.upbit()

def get_top_volume_coins():
    """상위 거래량 20개 KRW 코인 조회"""
    try:
        print("📡 업비트 거래량 정보 로딩 중...")
        
        # 모든 KRW 마켓 티커 정보 조회
        tickers = upbit.fetch_tickers()
        
        # KRW 마켓만 필터링
        krw_tickers = []
        for symbol, ticker in tickers.items():
            if symbol.endswith('/KRW'):
                krw_tickers.append({
                    'symbol': symbol,
                    'price': ticker['last'],
                    'volume': ticker['quoteVolume'],  # KRW 기준 거래량
                    'change_24h': ticker['percentage'],
                    'high_24h': ticker['high'],
                    'low_24h': ticker['low']
                })
        
        # 거래량 기준으로 정렬 (내림차순)
        krw_tickers.sort(key=lambda x: x['volume'] if x['volume'] else 0, reverse=True)
        
        # 상위 20개만 반환
        top_20 = krw_tickers[:20]
        
        print(f"✅ 상위 거래량 20개 코인 조회 완료")
        return top_20
        
    except Exception as e:
        print(f"❌ 거래량 정보 로딩 실패: {e}")
        return []

def display_top_volume_coins():
    """상위 거래량 20개 코인 리스트 출력"""
    print(f"\n📊 업비트 상위 거래량 20개 코인 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 100)
    
    top_coins = get_top_volume_coins()
    
    if not top_coins:
        print("❌ 거래량 정보를 가져올 수 없습니다.")
        return
    
    print(f"{'순위':<4} {'코인명':<15} {'현재가격':<15} {'24시간 거래량(KRW)':<20} {'24시간 변동률':<12} {'24시간 고가':<15} {'24시간 저가':<15}")
    print("-" * 100)
    
    for i, coin in enumerate(top_coins, 1):
        symbol_name = coin['symbol'].replace('/KRW', '')
        price = f"{coin['price']:,.0f}" if coin['price'] else "N/A"
        volume = f"{coin['volume']:,.0f}" if coin['volume'] else "N/A"
        change = f"{coin['change_24h']:+.2f}%" if coin['change_24h'] else "N/A"
        high = f"{coin['high_24h']:,.0f}" if coin['high_24h'] else "N/A"
        low = f"{coin['low_24h']:,.0f}" if coin['low_24h'] else "N/A"
        
        # 변동률에 따른 이모지
        if coin['change_24h']:
            if coin['change_24h'] > 0:
                emoji = "📈"
            elif coin['change_24h'] < 0:
                emoji = "📉"
            else:
                emoji = "➡️"
        else:
            emoji = "❓"
        
        print(f"{i:<4} {emoji} {symbol_name:<12} {price:<15} {volume:<20} {change:<12} {high:<15} {low:<15}")
    
    # 통계 정보
    total_volume = sum(coin['volume'] for coin in top_coins if coin['volume'])
    positive_coins = sum(1 for coin in top_coins if coin['change_24h'] and coin['change_24h'] > 0)
    negative_coins = sum(1 for coin in top_coins if coin['change_24h'] and coin['change_24h'] < 0)
    
    print("\n" + "=" * 100)
    print(f"📊 통계 요약:")
    print(f"   총 거래량: {total_volume:,.0f} KRW")
    print(f"   상승 코인: {positive_coins}개 ({positive_coins/20*100:.1f}%)")
    print(f"   하락 코인: {negative_coins}개 ({negative_coins/20*100:.1f}%)")
    print(f"   보합 코인: {20-positive_coins-negative_coins}개")
    
    if top_coins:
        avg_change = sum(coin['change_24h'] for coin in top_coins if coin['change_24h']) / len([c for c in top_coins if c['change_24h']])
        print(f"   평균 변동률: {avg_change:+.2f}%")

# 실행
if __name__ == "__main__":
    try:
        display_top_volume_coins()
        print("\n✅ 거래량 조회 완료!")
    except KeyboardInterrupt:
        print("\n⏹️ 프로그램 중단됨")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")