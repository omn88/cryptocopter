import backtrader as bt


class BasicRSISignal(bt.Indicator):
    lines = (
        "buy_signal",
        "sell_signal",
    )
    params = (
        ("rsi_low", 30),
        ("rsi_high", 70),
        ("dca_orders", 4),
        ("dca_span", 0.005),
    )

    def __init__(self):
        self.rsi = bt.ind.RSI(self.data.close)
        super(BasicRSISignal, self).__init__()

    def next(self):
        # Buy signals
        if (
            self.rsi[-2] < self.p.rsi_low
            and self.rsi[-1] > self.p.rsi_low
            and self.rsi[0] > self.p.rsi_low
        ):
            self.lines.buy_signal[0] = True
        else:
            self.lines.buy_signal[0] = False

        # Sell signals
        if (
            self.rsi[-2] > self.p.rsi_high
            and self.rsi[-1] < self.p.rsi_high
            and self.rsi[0] < self.p.rsi_high
        ):
            self.lines.sell_signal[0] = True
        else:
            self.lines.sell_signal[0] = False
