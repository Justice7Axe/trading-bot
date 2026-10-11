import os
import sys
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.config import load_settings
from kiwoom_trading.common.storage import SupabaseReader

KST_TZ = "Asia/Seoul"


def _to_abs_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return None


def _fmt_krw(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{int(round(value)):,.0f}원"


def _calc_rsi(price_series: pd.Series, period: int = 14) -> pd.Series:
    delta = price_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(0)


def _minute_key(row: dict[str, Any]) -> str:
    raw_values = row.get("raw_values")
    if isinstance(raw_values, dict):
        snapshot_minute = raw_values.get("snapshot_minute")
        if isinstance(snapshot_minute, str) and snapshot_minute.strip():
            return snapshot_minute.strip()
    collected_at = str(row.get("collected_at") or "")
    if not collected_at:
        return ""
    normalized = collected_at.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    return dt.strftime("%Y%m%d%H%M")


def build_minute_df(rows_desc: list[dict[str, Any]]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in rows_desc:
        minute_key = _minute_key(row)
        if minute_key == "":
            continue
        price = _to_abs_float(row.get("current_price"))
        if price is None:
            continue
        records.append(
            {
                "minute_key": minute_key,
                "stock_code": str(row.get("stock_code") or ""),
                "price": price,
                "collected_at": row.get("collected_at"),
            }
        )

    if not records:
        return pd.DataFrame(columns=["minute_time", "stock_code", "price", "collected_at"])

    df = pd.DataFrame(records)
    df["minute_time"] = pd.to_datetime(df["minute_key"], format="%Y%m%d%H%M", errors="coerce").dt.tz_localize(KST_TZ)
    df = df.dropna(subset=["minute_time"])
    df = df.sort_values(["stock_code", "minute_time", "collected_at"], ascending=[True, True, True])
    df = df.drop_duplicates(subset=["stock_code", "minute_key"], keep="last")
    df = df.sort_values("minute_time", ascending=True)
    df["sma_5"] = df.groupby("stock_code")["price"].transform(lambda s: s.rolling(5).mean())
    df["sma_20"] = df.groupby("stock_code")["price"].transform(lambda s: s.rolling(20).mean())
    rolling_std_20 = df.groupby("stock_code")["price"].transform(lambda s: s.rolling(20).std())
    df["bb_upper"] = df["sma_20"] + (rolling_std_20 * 2)
    df["bb_lower"] = df["sma_20"] - (rolling_std_20 * 2)
    df["rsi_14"] = df.groupby("stock_code")["price"].transform(lambda s: _calc_rsi(s, 14))
    return df


def _build_single_stock_figure(code_df: pd.DataFrame, stock_code: str, legend_preset: str) -> go.Figure:
    buy_points = code_df[code_df["rsi_14"] <= 30]
    sell_points = code_df[code_df["rsi_14"] >= 70]
    strategy_buy_points = code_df[code_df["strategy_buy"]]
    strategy_sell_points = code_df[code_df["strategy_sell"]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=code_df["minute_time"],
            y=code_df["price"],
            mode="lines+markers",
            name=f"{stock_code} Price",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=code_df["minute_time"],
            y=code_df["sma_5"],
            mode="lines",
            name="SMA 5",
            line={"width": 1.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=code_df["minute_time"],
            y=code_df["sma_20"],
            mode="lines",
            name="SMA 20",
            line={"width": 1.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=code_df["minute_time"],
            y=code_df["bb_upper"],
            mode="lines",
            name="BB Upper(20,2)",
            line={"dash": "dot", "width": 1},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=code_df["minute_time"],
            y=code_df["bb_lower"],
            mode="lines",
            name="BB Lower(20,2)",
            line={"dash": "dot", "width": 1},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=buy_points["minute_time"],
            y=buy_points["price"],
            mode="markers",
            name="Buy Signal (RSI<=30)",
            marker={"color": "green", "size": 10, "symbol": "triangle-up"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=sell_points["minute_time"],
            y=sell_points["price"],
            mode="markers",
            name="Sell Signal (RSI>=70)",
            marker={"color": "red", "size": 10, "symbol": "triangle-down"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=strategy_buy_points["minute_time"],
            y=strategy_buy_points["price"],
            mode="markers",
            name="Strategy Buy (RSI+GoldenCross)",
            marker={"color": "lime", "size": 13, "symbol": "star"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=strategy_sell_points["minute_time"],
            y=strategy_sell_points["price"],
            mode="markers",
            name="Strategy Sell (RSI+DeadCross)",
            marker={"color": "orange", "size": 13, "symbol": "x"},
        )
    )

    visibility_map = {
        "전체": [True, True, True, True, True, True, True, True, True],
        "가격+이평": [True, True, True, False, False, False, False, False, False],
        "가격+볼린저": [True, False, False, True, True, False, False, False, False],
        "가격+시그널": [True, False, False, False, False, True, True, False, False],
        "가격+전략시그널": [True, False, False, False, False, False, False, True, True],
    }
    selected_visibility = visibility_map.get(legend_preset, visibility_map["전체"])
    for trace, visible in zip(fig.data, selected_visibility):
        trace.visible = True if visible else "legendonly"

    fig.update_layout(
        title=f"{stock_code} 분봉 차트 (프리셋: {legend_preset})",
        xaxis_title="시간(KST)",
        yaxis_title="가격(KRW)",
        legend_title="지표",
    )
    fig.update_yaxes(tickprefix="₩", tickformat=",.0f")
    return fig


def main() -> None:
    st.set_page_config(page_title="Kiwoom 주가 차트", layout="wide")
    st.title("Kiwoom DB 주가 차트")
    st.caption("시간 기준: 한국시간(KST) / 가격 기준: 원화(KRW)")

    settings = load_settings()
    reader = SupabaseReader(
        supabase_url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
        table_name=settings.supabase_table,
    )

    st.sidebar.header("옵션")
    auto_refresh = st.sidebar.checkbox("60초 자동 새로고침", value=True)
    if auto_refresh:
        st_autorefresh(interval=60_000, key="kiwoom_chart_refresh")

    selected_codes = st.sidebar.multiselect(
        "종목 선택",
        settings.stock_codes,
        default=settings.stock_codes,
    )
    time_range = st.sidebar.selectbox("구간 확대", ["최근 1시간", "당일", "전체"], index=0)
    legend_preset = st.sidebar.selectbox(
        "지표 범례 토글 프리셋",
        ["전체", "가격+이평", "가격+볼린저", "가격+시그널", "가격+전략시그널"],
        index=0,
    )
    enable_strategy_signal = st.sidebar.checkbox("전략 시그널 표시(RSI + SMA 교차)", value=True)
    rsi_buy_threshold = st.sidebar.slider("RSI 매수 임계값", min_value=10, max_value=40, value=30)
    rsi_sell_threshold = st.sidebar.slider("RSI 매도 임계값", min_value=60, max_value=90, value=70)
    fetch_limit = st.sidebar.slider("조회 건수(종목별)", min_value=100, max_value=5000, value=1000, step=100)

    if not selected_codes:
        st.warning("최소 1개 종목을 선택해주세요.")
        return

    all_rows: list[dict[str, Any]] = []
    for code in selected_codes:
        rows = reader.fetch_recent_by_stock(stock_code=code, limit=fetch_limit)
        all_rows.extend(rows)

    df = build_minute_df(all_rows)
    if df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    latest_time = df["minute_time"].max()
    if time_range == "최근 1시간":
        df = df[df["minute_time"] >= (latest_time - pd.Timedelta(hours=1))]
    elif time_range == "당일":
        df = df[df["minute_time"].dt.date == latest_time.date()]

    latest = df.sort_values("minute_time").groupby("stock_code", as_index=False).tail(1).sort_values("stock_code")
    cols = st.columns(len(latest))
    for i, row in enumerate(latest.itertuples(index=False)):
        code_df = df[df["stock_code"] == row.stock_code]
        prev_price = code_df.iloc[-2]["price"] if len(code_df) >= 2 else None
        delta = row.price - prev_price if prev_price is not None else None
        delta_pct = (delta / prev_price * 100) if prev_price not in (None, 0) else None
        delta_text = "N/A" if delta is None else f"{delta:+,.0f}원 ({delta_pct:+.2f}%)"
        cols[i].metric(
            label=f"{row.stock_code}",
            value=_fmt_krw(row.price),
            delta=delta_text,
        )

    tabs = st.tabs([f"{code}" for code in selected_codes])
    for tab, code in zip(tabs, selected_codes):
        with tab:
            code_df = df[df["stock_code"] == code].sort_values("minute_time", ascending=True).copy()
            if code_df.empty:
                st.info("해당 종목 데이터가 없습니다.")
                continue

            # SMA 교차 여부 계산
            sma_gap = code_df["sma_5"] - code_df["sma_20"]
            prev_gap = sma_gap.shift(1)
            golden_cross = (sma_gap > 0) & (prev_gap <= 0)
            dead_cross = (sma_gap < 0) & (prev_gap >= 0)

            if enable_strategy_signal:
                code_df["strategy_buy"] = golden_cross & (code_df["rsi_14"] <= rsi_buy_threshold)
                code_df["strategy_sell"] = dead_cross & (code_df["rsi_14"] >= rsi_sell_threshold)
            else:
                code_df["strategy_buy"] = False
                code_df["strategy_sell"] = False

            fig = _build_single_stock_figure(code_df, code, legend_preset)
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Price + SMA(5/20) + Bollinger Bands(20,2) + RSI(14) + 전략 시그널")

            strategy_buy_count = int(code_df["strategy_buy"].sum())
            strategy_sell_count = int(code_df["strategy_sell"].sum())
            st.write(f"전략 시그널 집계: 매수 {strategy_buy_count}건 / 매도 {strategy_sell_count}건")
            st.dataframe(
                code_df[
                    [
                        "minute_time",
                        "price",
                        "sma_5",
                        "sma_20",
                        "bb_upper",
                        "bb_lower",
                        "rsi_14",
                        "strategy_buy",
                        "strategy_sell",
                    ]
                ]
                .tail(100)
                .rename(
                    columns={
                        "minute_time": "시간(KST)",
                        "price": "가격(원)",
                        "sma_5": "SMA5(원)",
                        "sma_20": "SMA20(원)",
                        "bb_upper": "BB상단(원)",
                        "bb_lower": "BB하단(원)",
                        "rsi_14": "RSI14",
                        "strategy_buy": "전략매수",
                        "strategy_sell": "전략매도",
                    }
                ),
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
