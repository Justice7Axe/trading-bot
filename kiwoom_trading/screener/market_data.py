"""스크리너용 키움 REST 조회 (조회 순위, 거래대금 상위, 종목 시세, 종목 테마)."""
from dataclasses import dataclass
from typing import Any, Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient, _to_int


def _code(value: Any) -> str:
    """'005930_AL', 'A005930' → '005930'"""
    text = str(value or "").strip()
    if text.startswith("A"):
        text = text[1:]
    return text.split("_")[0]


def _rate(value: Any) -> Optional[float]:
    text = str(value if value is not None else "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text) / 100
    except ValueError:
        return None


@dataclass(frozen=True)
class RankItem:
    code: str
    name: str
    rank: int
    change_rate: Optional[float] = None       # 등락률 (0.05 = +5%)
    price: Optional[int] = None
    trade_value: Optional[int] = None         # 원
    as_of: str = ""                           # 'YYYYMMDD' (조회 순위 데이터 기준일, 휴장일 판별용)


@dataclass(frozen=True)
class Quote:
    code: str
    name: str
    open: int
    high: int
    low: int
    price: int
    base_price: int                           # 전일 종가(기준가)
    volume: int
    high_250: Optional[int] = None
    upper: Optional[int] = None                # 거래소가 정한 오늘 상한가 (upl_pric) — 신규 상장 첫날은 공모가의 400%


@dataclass(frozen=True)
class Theme:
    code: str
    name: str
    change_rate: Optional[float]              # 테마 등락률
    members: int
    rising: int
    falling: int
    main_stocks: str = ""


class KiwoomMarket:
    def __init__(self, client: KiwoomDailyClient) -> None:
        self.client = client

    def search_rank(self, qry_tp: str = "4") -> list[RankItem]:
        """ka00198 실시간 종목 조회 순위. qry_tp 1:1분 2:10분 3:1시간 4:당일 누적 5:30초"""
        payload, _, _ = self.client._post("/api/dostk/stkinfo", "ka00198", {"qry_tp": qry_tp})
        items = []
        for row in payload.get("item_inq_rank") or []:
            items.append(RankItem(
                code=_code(row.get("stk_cd")), name=str(row.get("stk_nm") or ""),
                rank=_to_int(row.get("bigd_rank")) or 0, change_rate=_rate(row.get("base_comp_chgr")),
                price=_to_int(row.get("past_curr_prc")), as_of=str(row.get("dt") or ""),
            ))
        return items

    def value_rank(self, pages: int = 1, stex_tp: str = "1") -> list[RankItem]:
        """ka10032 거래대금 상위 (관리종목 제외). 1페이지 = 100종목.

        stex_tp 1: KRX(기본, 일봉 DB 와 같은 기준) / 2: NXT / 3: 통합
        """
        items: list[RankItem] = []
        cont, next_key = "N", ""
        for _ in range(pages):
            payload, cont, next_key = self.client._post(
                "/api/dostk/rkinfo", "ka10032", {"mrkt_tp": "000", "mang_stk_incls": "0", "stex_tp": stex_tp}, cont, next_key
            )
            for row in payload.get("trde_prica_upper") or []:
                sign = -1 if str(row.get("flu_rt", "")).startswith("-") else 1
                rate = _rate(str(row.get("flu_rt", "")).lstrip("+-"))
                value_mil = _to_int(row.get("trde_prica"))
                items.append(RankItem(
                    code=_code(row.get("stk_cd")), name=str(row.get("stk_nm") or ""),
                    rank=_to_int(row.get("now_rank")) or len(items) + 1,
                    change_rate=sign * rate if rate is not None else None,
                    price=_to_int(row.get("cur_prc")),
                    trade_value=value_mil * 1_000_000 if value_mil is not None else None,
                ))
            if cont != "Y" or not next_key:
                break
        return items

    def risers(self, min_value_cond: str = "300", stex_tp: str = "3", pages: int = 1) -> list[RankItem]:
        """ka10027 전일대비 등락률 상위 (ETF·ETN 제외, 상한가 포함). 1페이지 = 200종목.

        min_value_cond: 거래대금 조건 '300' = 30억↑, '1000' = 100억↑ (키움 코드값)
        stex_tp 3: 통합(KRX+NXT) — 08:00 프리마켓 급등도 잡기 위해. trade_value = 현재 거래량 × 현재가 (근사)
        """
        items: list[RankItem] = []
        cont, next_key = "N", ""
        for _ in range(pages):
            payload, cont, next_key = self.client._post(
                "/api/dostk/rkinfo", "ka10027",
                {"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "0000", "stk_cnd": "16", "crd_cnd": "0",
                 "updown_incls": "1", "pric_cnd": "0", "trde_prica_cnd": min_value_cond, "stex_tp": stex_tp},
                cont, next_key,
            )
            for row in payload.get("pred_pre_flu_rt_upper") or []:
                sign = -1 if str(row.get("flu_rt", "")).startswith("-") else 1
                rate = _rate(str(row.get("flu_rt", "")).lstrip("+-"))
                price = _to_int(row.get("cur_prc"))
                qty = _to_int(row.get("now_trde_qty"))
                items.append(RankItem(
                    code=_code(row.get("stk_cd")), name=str(row.get("stk_nm") or ""), rank=len(items) + 1,
                    change_rate=sign * rate if rate is not None else None, price=price,
                    trade_value=price * qty if price and qty else None,
                ))
            if cont != "Y" or not next_key:
                break
        return items

    def quote(self, code: str, integrated: bool = True) -> Optional[Quote]:
        """ka10001 주식기본정보 (당일 시가/고가/저가/현재가, 250일 최고가).

        integrated=True: '_AL'(KRX+NXT 통합) 시세 — 08:00~09:00 프리마켓·애프터마켓 체결까지 반영 (가격 판단용)
        integrated=False: KRX 시세 — 거래량을 KRX 기준으로 볼 때
        """
        stk_cd = f"{code}_AL" if integrated else code
        payload, _, _ = self.client._post("/api/dostk/stkinfo", "ka10001", {"stk_cd": stk_cd})
        price = _to_int(payload.get("cur_prc"))
        if not price:
            return None
        return Quote(
            code=code, name=str(payload.get("stk_nm") or ""),
            open=_to_int(payload.get("open_pric")) or price, high=_to_int(payload.get("high_pric")) or price,
            low=_to_int(payload.get("low_pric")) or price, price=price,
            base_price=_to_int(payload.get("base_pric")) or price, volume=_to_int(payload.get("trde_qty")) or 0,
            high_250=_to_int(payload.get("250hgst")), upper=_to_int(payload.get("upl_pric")),
        )

    def investor_intraday(self, investor: str, max_pages: int = 10) -> dict[str, int]:
        """ka10063 장중 투자자별 순매수(잠정치, KRX) 전 종목. investor: '6' 외국인, '7' 기관계. 반환 코드 → 순매수 금액(원).

        KRX 잠정치라 하루 5~6번(09:20 무렵부터)만 갱신된다. 부호는 '--288' 처럼 '-' 가 겹쳐 올 수 있다.
        """
        out: dict[str, int] = {}
        cont, next_key = "N", ""
        for _ in range(max_pages):
            payload, cont, next_key = self.client._post(
                "/api/dostk/mrkcond", "ka10063",
                {"mrkt_tp": "000", "amt_qty_tp": "1", "invsr": investor, "frgn_all": "0", "smtm_netprps_tp": "0", "stex_tp": "1"},
                cont, next_key,
            )
            for row in payload.get("opmr_invsr_trde") or []:
                text = str(row.get("netprps_amt") or "0").replace(",", "").strip()
                negative = text.startswith("-")
                try:
                    amount = int(float(text.lstrip("+-") or 0)) * 1_000_000
                except ValueError:
                    continue
                out[_code(row.get("stk_cd"))] = -amount if negative else amount
            if cont != "Y" or not next_key:
                break
        return out

    def program_intraday(self, day: str, max_pages: int = 100) -> dict[str, tuple[int, int, int]]:
        """ka90004 종목별 프로그램 매매(KRX) 코스피+코스닥 전 종목 → 코드 → (매수, 매도, 순매수) 금액(원), 장 시작부터 누적.

        day: 'YYYYMMDD' — 넣어도 마지막 거래일 값만 오므로 장중에 쌓아야 한다. 전 종목 약 74쪽·18초.
        외인 방향 대용으로 잠정치보다 정확하다 (10-23 하루: 10:00 74%, 15:00 86% vs 잠정치 마감 값 70%).
        """
        out: dict[str, tuple[int, int, int]] = {}

        def won(value: Any) -> int:
            text = str(value or "0").replace(",", "").strip()
            try:
                amount = int(float(text.lstrip("+-") or 0)) * 1_000_000
            except ValueError:
                return 0
            return -amount if text.startswith("-") else amount

        for market_tp in ("P00101", "P10102"):
            cont, next_key = "N", ""
            for _ in range(max_pages):
                payload, cont, next_key = self.client._post(
                    "/api/dostk/stkinfo", "ka90004", {"dt": day, "mrkt_tp": market_tp, "stex_tp": "1"}, cont, next_key,
                )
                for row in payload.get("stk_prm_trde_prst") or []:
                    out[_code(row.get("stk_cd"))] = (won(row.get("buy_cntr_amt")), won(row.get("sel_cntr_amt")),
                                                     won(row.get("netprps_prica")))
                if cont != "Y" or not next_key:
                    break
        return out

    def theme_groups(self) -> list[Theme]:
        """ka90001 (qry_tp=0): 전체 테마 목록과 당일 등락률/상승 종목 수.

        종목별 테마 조회(qry_tp=2)는 대부분 종목에서 빈 결과라 쓰지 않는다 → 구성 종목(ka90002)으로 직접 매핑.
        """
        themes: list[Theme] = []
        cont, next_key = "N", ""
        for _ in range(10):
            payload, cont, next_key = self.client._post(
                "/api/dostk/thme", "ka90001",
                {"qry_tp": "0", "stk_cd": "", "date_tp": "1", "thema_nm": "", "flu_pl_amt_tp": "1", "stex_tp": "1"},
                cont, next_key,
            )
            for row in payload.get("thema_grp") or []:
                themes.append(Theme(
                    code=str(row.get("thema_grp_cd") or ""), name=str(row.get("thema_nm") or ""),
                    change_rate=_rate(row.get("flu_rt")), members=_to_int(row.get("stk_num")) or 0,
                    rising=_to_int(row.get("rising_stk_num")) or 0, falling=_to_int(row.get("fall_stk_num")) or 0,
                    main_stocks=str(row.get("main_stk") or ""),
                ))
            if cont != "Y" or not next_key:
                break
        return themes

    def theme_members(self, theme_code: str) -> list[str]:
        """ka90002 테마 구성 종목 코드."""
        payload, _, _ = self.client._post("/api/dostk/thme", "ka90002", {"date_tp": "1", "thema_grp_cd": theme_code, "stex_tp": "1"})
        return [_code(row.get("stk_cd")) for row in payload.get("thema_comp_stk") or []]
