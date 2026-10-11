import os
import sys
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, List

import matplotlib
import requests
from dotenv import load_dotenv

# 한글 폰트 및 마이너스 표시가 깨지지 않도록 설정
matplotlib.rcParams["font.family"] = [
    "Malgun Gothic",  # Windows
    "AppleGothic",  # macOS
    "NanumGothic",  # Linux에서 자주 사용
    "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False


def _configure_utf8_console() -> None:
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.SetConsoleCP(65001)
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


@dataclass(frozen=True)
class SupabaseSettings:
    supabase_url: str
    service_role_key: str
    source_table: str


def _load_settings() -> SupabaseSettings:
    load_dotenv(".env.local")
    supabase_url = (os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL") or "").rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    source_table = os.getenv("KIWOOM_TOP_VALUE_SUPABASE_TABLE", "kiwoom_top_value_minute")

    if not supabase_url or not service_role_key:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수를 확인해주세요.")

    return SupabaseSettings(
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        source_table=source_table,
    )


def _fetch_rows_for_stock_and_date(
    settings: SupabaseSettings,
    stock_name: str,
    target_date: date,
) -> list[dict[str, Any]]:
    headers = {
        "apikey": settings.service_role_key,
        "Authorization": f"Bearer {settings.service_role_key}",
    }

    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)

    # PostgREST 는 같은 컬럼에 대해 여러 조건을 줄 때
    # `collected_at=gte....&collected_at=lt....` 와 같이
    # 동일 키를 두 번 보내는 방식을 사용합니다.
    params = [
        (
            "select",
            "id,collected_at,snapshot_minute,stock_code,stock_name,"
            "current_price,change_rate,cum_trade_value,trade_value_rank",
        ),
        ("stock_name", f"eq.{stock_name}"),
        ("collected_at", f"gte.{start.isoformat()}"),
        ("collected_at", f"lt.{end.isoformat()}"),
        ("order", "collected_at.asc,trade_value_rank.asc"),
        ("limit", "5000"),
    ]

    response = requests.get(
        f"{settings.supabase_url}/rest/v1/{settings.source_table}",
        headers=headers,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return data
    return []


def _parse_snapshot_times(rows: list[dict[str, Any]]) -> List[datetime]:
    times: List[datetime] = []
    for row in rows:
        # snapshot_minute 는 텍스트 포맷이 제각각일 수 있으므로
        # Supabase 가 ISO 포맷으로 내려주는 collected_at 기준으로만 파싱한다.
        snap = row.get("collected_at")
        if not isinstance(snap, str):
            continue
        try:
            times.append(datetime.fromisoformat(snap.replace("Z", "+00:00")))
        except Exception:
            continue
    return times


def _extract_series(
    rows: list[dict[str, Any]],
) -> tuple[List[datetime], List[float], List[float], List[int]]:
    xs: List[datetime] = []
    values: List[float] = []
    ranks: List[int] = []
    changes: List[float] = []

    for row in rows:
        # 시간 축도 collected_at 기준으로만 사용
        snap = row.get("collected_at")
        if not isinstance(snap, str):
            continue
        try:
            x = datetime.fromisoformat(snap.replace("Z", "+00:00"))
        except Exception:
            continue
        xs.append(x)
        values.append(float(row.get("cum_trade_value") or 0))
        ranks.append(int(row.get("trade_value_rank") or 0))
        changes.append(float(row.get("change_rate") or 0.0))

    return xs, values, changes, ranks


def _print_summary(
    stock_name: str,
    target_date: date,
    rows: list[dict[str, Any]],
) -> None:
    print("=== 거래대금 상위 스냅샷 단일 종목 분석 ===")
    print(f"- 종목명: {stock_name}")
    print(f"- 날짜: {target_date.isoformat()}")
    print(f"- 행 개수: {len(rows)}")

    if not rows:
        return

    times = _parse_snapshot_times(rows)
    if times:
        print(f"- 첫 스냅샷: {min(times)}")
        print(f"- 마지막 스냅샷: {max(times)}")

    trade_values = [float(r.get("cum_trade_value") or 0) for r in rows]
    ranks = [int(r.get("trade_value_rank") or 0) for r in rows if r.get("trade_value_rank") is not None]
    changes = [float(r.get("change_rate") or 0.0) for r in rows if r.get("change_rate") is not None]

    if trade_values:
        print(
            f"- 거래대금: min={min(trade_values):,.0f} max={max(trade_values):,.0f} "
            f"last={trade_values[-1]:,.0f}"
        )
    if ranks:
        print(f"- 거래대금 순위: best={min(ranks)} worst={max(ranks)} last={ranks[-1]}")
    if changes:
        print(
            f"- 주가 등락률(%) 범위: min={min(changes):.2f} max={max(changes):.2f} "
            f"last={changes[-1]:.2f}"
        )


def _save_chart(
    stock_name: str,
    target_date: date,
    rows: list[dict[str, Any]],
    out_dir: str,
) -> str | None:
    if not rows:
        return None

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib 이 설치되어 있지 않아 차트를 생성할 수 없습니다. `pip install matplotlib` 후 다시 실행해주세요.")
        return None

    xs, trade_values, changes, ranks = _extract_series(rows)
    if not xs:
        print("시간 축 데이터를 파싱하지 못해 차트를 생성할 수 없습니다.")
        return None

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

    ax1.plot(xs, trade_values, label="누적 거래대금", color="tab:blue")
    ax1.set_ylabel("누적 거래대금")
    ax1.grid(True, alpha=0.3)

    ax2.plot(xs, ranks, label="거래대금 순위 (작을수록 상위)", color="tab:orange")
    ax2.invert_yaxis()
    ax2.set_ylabel("거래대금 순위")
    ax2.grid(True, alpha=0.3)

    ax3.plot(xs, changes, label="주가 등락률(%)", color="tab:green")
    ax3.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax3.set_ylabel("등락률(%)")
    ax3.grid(True, alpha=0.3)

    fig.suptitle(f"{stock_name} | {target_date.isoformat()} 거래대금/순위/등락률")
    fig.autofmt_xdate()

    # 한글 y축 라벨이 잘리지 않도록 좌측 여백을 넉넉히 확보
    fig.subplots_adjust(left=0.13, right=0.98, top=0.93, bottom=0.07, hspace=0.15)

    os.makedirs(out_dir, exist_ok=True)
    safe_name = stock_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    filename = f"{safe_name}_{target_date.isoformat()}_top_value_analysis.png"
    out_path = os.path.join(out_dir, filename)

    plt.savefig(out_path, dpi=150)
    plt.close(fig)

    print(f"차트 저장 완료: {out_path}")
    return out_path


def main() -> None:
    _configure_utf8_console()
    settings = _load_settings()

    stock_name = os.getenv("BACKTEST_STOCK_NAME", "우리기술")
    date_str = os.getenv("BACKTEST_TARGET_DATE")
    if not date_str:
        # 기본값: 오늘 날짜 기준
        target_date = date.today()
    else:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    rows = _fetch_rows_for_stock_and_date(
        settings=settings,
        stock_name=stock_name,
        target_date=target_date,
    )

    _print_summary(stock_name=stock_name, target_date=target_date, rows=rows)
    _save_chart(
        stock_name=stock_name,
        target_date=target_date,
        rows=rows,
        out_dir=os.path.dirname(__file__),
    )


if __name__ == "__main__":
    main()

