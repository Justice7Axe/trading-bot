from datetime import date

from kiwoom_trading.strategies.event_scenario.live import ex_date, next_trading


def test_ex_date_future_weekday():
    # 기준일 2026-11-10(화) → 마지막 거래일 11-10 → 권리락일 11-09(월)
    assert ex_date(date(2026, 11, 10), [], date(2026, 10, 29)) == date(2026, 11, 9)


def test_ex_date_record_on_holiday():
    # 기준일 12-31(휴장) → 마지막 거래일 12-30(수) → 권리락일 12-29(화)
    assert ex_date(date(2026, 12, 31), [], date(2026, 10, 29)) == date(2026, 12, 29)


def test_ex_date_monday_record():
    # 기준일 11-16(월) → 권리락일 11-13(금)
    assert ex_date(date(2026, 11, 16), [], date(2026, 10, 29)) == date(2026, 11, 13)


def test_next_trading_skips_weekend_and_holiday():
    assert next_trading(date(2026, 10, 30)) == date(2026, 11, 2)
    assert next_trading(date(2026, 12, 24)) == date(2026, 12, 28)
