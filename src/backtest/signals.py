import backtrader as bt


class BasicRsiSignal(bt.Indicator):
    lines = (
        "buy_signal",
        "sell_signal",
    )
    params = (
        ("rsi_low", 30),
        ("rsi_high", 70),
    )

    def __init__(self):
        self.rsi = bt.ind.RSI(self.data.close)
        super(BasicRsiSignal, self).__init__()

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


class ExtendedRsiSignal(bt.Indicator):
    lines = (
        "buy_signal",
        "sell_signal",
    )
    params = (
        ("rsi_low", 20),
        ("rsi_high", 80),
    )

    def __init__(self):
        self.rsi = bt.ind.RSI(self.data.close)
        super(ExtendedRsiSignal, self).__init__()

    def next(self):
        # Buy signals
        if self.rsi[-1] < self.p.rsi_low and self.rsi[0] > self.p.rsi_low:
            self.lines.buy_signal[0] = True
        else:
            self.lines.buy_signal[0] = False

        # Sell signals
        if self.rsi[-1] > self.p.rsi_high and self.rsi[0] < self.p.rsi_high:
            self.lines.sell_signal[0] = True
        else:
            self.lines.sell_signal[0] = False
