"""🔺 홍인기 D+ 매매 규칙 — 백테스트·실시간 공용 (홍인기 파이널 3·4·5강, 2026-11-02 정리, 스킬 hong-dplus).

D+0 = 주도 섹터(테마) 대장주로 첫 장대양봉이 나온 날, D+1·D+2 = 그다음 날·다다음 날.
  · 주도 섹터: 대금 상위 20위 안에서 +5%↑ 종목이 3개↑ 인 테마 (5개↑ 초강세). 09:20 부터 보고, 09:30 전에는 사지 않음.
  · 대장주: 그 섹터 종목 중 대금 20위 안에서 등락률이 가장 높은 종목.
  · 걸러내기 (강의 그대로): 최근 강했던 섹터 / 과거 대장을 했던 종목(처음 대장 X) / 장대양봉 뒤 2주(10거래일) 지난 자리 /
    시총 5천억↑ / 지수 하락 날 D+0 X / KRX 갭상승(프리장 강세) 종목 D+0 주의 / 신고가에 가까운 일봉 자리 / 끼(최근 3달 크게 오른 적).
  · D+1·D+2: D+0 에서 대장으로 마감한 종목, 갭상승 출발만, 전일 종가 지지 눌림 매수, 같은 섹터 D+ 종목 중 가장 강한 것.
"""
import re
from collections import defaultdict

# 섹터가 아닌 네이버 테마 (지수 편입·대형주 묶음·그룹·상장 시기) — 강의의 '섹터'(반도체·로봇·원전…)와 달라 뺌 (2026-11-02 사용자 '빼고 다시 검증')
NON_SECTOR = re.compile(r"밸류업|지수|S7|대표주|지주사|신규상장|SPAC|자산주|환율")

TOP, UP, NMIN = 20, 0.05, 3          # 대금 20위 · +5%↑ · 3개↑
BIG = 0.10                           # 장대양봉 (그날 +10%↑ 상승 마감)
QUIET = 10                           # 장대양봉 뒤 10거래일 (2주) 지난 자리
RECENT = 20                          # 최근 강세 섹터 = 지난 20거래일 안에 주도 섹터였던 적
PAST_LEAD = 60                       # 과거 대장 = 지난 60거래일 안에 대장이었던 적
KKI_DAYS, KKI_UP = 60, 0.25          # 끼 = 지난 60거래일 안에 3일 동안 +25%↑ 오른 적
MCAP_MIN = 5e11                      # 시총 5천억↑
BIG_CAP = 2e12                       # 시총 2조↑ 대형주 대장 (장중 매매+상따), 아래는 상따 위주
NEAR_HIGH = 0.92                     # 전날까지 250일 고가의 92%↑ (신고가를 터치할 가능성 높은 자리)
GAP_MAX = 0.05                       # D+0 KRX 갭 +5%↑ 는 주의 → 뺌
OBSERVE, FIRST_BUY, LAST_BUY = (9, 20), (9, 30), (10, 30)


def lead_themes(rows, themes, top=TOP, up=UP, nmin=NMIN):
    """rows = [(code, 등락률, 대금)] (대금 순서 무관) → (주도 테마 {테마: [(code, 등락률)]}, 대장 {code: 테마}).
    대금 상위 top 안에서 등락률 up↑ 종목이 nmin 개↑ 인 테마가 주도 테마, 그 안 등락률 1위가 대장.
    한 종목이 여러 테마 대장이면 +5%↑ 종목이 가장 많은 테마로."""
    ranked = sorted(rows, key=lambda r: -(r[2] or 0))[:top]
    mem = defaultdict(list)
    for code, ch, _ in ranked:
        if ch is not None and ch >= up:
            for th in themes.get(code, ()):
                mem[th].append((code, ch))
    lead = {th: m for th, m in mem.items() if len(m) >= nmin}
    leaders = {}
    for th, m in lead.items():
        code = max(m, key=lambda x: x[1])[0]
        if code not in leaders or len(m) > len(lead[leaders[code]]):
            leaders[code] = th
    return lead, leaders
