from datetime import datetime

import binance
import pandas
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from decouple import config
import lib

COLOR_RSI = "#8548CC"
COLOR_PURPLE_AREA = "#DBC3F8"

client = binance.Client(api_key=config("API_KEY"), api_secret=config("API_SECRET"))


def gather_data(start_date: str, end_date: str) -> pandas.DataFrame:
    fmt = "%Y-%m-%d %H:%M:%S"
    d1 = datetime.strptime(start_date, fmt)
    d2 = datetime.strptime(end_date, fmt)
    dnow = datetime.now()

    days_diff_from_now = (dnow - d1).days
    lookback = days_diff_from_now * 24 * 60

    days_end_from_now = (dnow - d2).days
    end_str = days_end_from_now * 24 * 60

    df = lib.get_futures_historical_data_sync(
        client=client,
        symbol="BTCUSDT",
        interval="15m",
        lookback=str(lookback),  # 44000 is approximately one month
        look_end=str(end_str),
    )

    lib.calc_indicators(df=df)

    return df


def plot_figure(df: pandas.DataFrame):
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.01, row_heights=[0.7, 0.3]
    )

    # Plot Price with candlesticks
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df.Open,
            high=df.High,
            low=df.Low,
            close=df.Close,
            name="Price",
        )
    )

    # Plot grey area for RSI
    rectangle_x_all_values = [
        df.index[0],
        df.index[0],
        df.index[-1],
        df.index[-1],
        df.index[0],
    ]
    rectangle_y_from_thirty_to_seventy = [30, 70, 70, 30, 30]

    fig.add_trace(
        go.Scatter(
            x=rectangle_x_all_values,
            y=rectangle_y_from_thirty_to_seventy,
            fill="toself",
            line=dict(color=COLOR_PURPLE_AREA),
        ),
        row=2,
        col=1,
    )

    # Plot RSI
    fig.add_trace(
        go.Scatter(x=df.index, y=df.RSI, name="RSI", line=dict(color=COLOR_RSI)),
        row=2,
        col=1,
    )
    fig.add_hline(y=80, line_dash="dash", row=2, col=1, line_width=1)
    fig.add_hline(y=50, row=2, col=1, line_width=1)
    fig.add_hline(y=20, line_dash="dash", row=2, col=1, line_width=1)

    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1)

    fig.update_layout(height=900, width=1800, xaxis_rangeslider_visible=False)

    fig.show()


def plot_price_and_rsi(start_date: str, end_date: str) -> None:
    df = gather_data(start_date=start_date, end_date=end_date)
    plot_figure(df=df)


plot_price_and_rsi(start_date="2021-01-01 00:00:00", end_date="2021-03-01 00:00:00")
