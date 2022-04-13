import PySimpleGUI as sg

sg.theme("Default")  # Add a touch of color
user_input = [
    [
        sg.Text("Symbol:"),
        sg.InputText(size=(10, 1), key="-SYMBOL-", default_text="BTCUSDT"),
        sg.Text("Budget: "),
        sg.Input(size=(10, 1), key="-BUDGET-", default_text="200"),
        sg.Text("Status:"),
        sg.Text("Fresh"),
    ]
]
user_input_control = [
    [
        sg.Button("Start", key="-START_STRATEGY-"),
        sg.Button("Exit", key="-EXIT_STRATEGY-"),
    ],
]
indicators = [
    [
        sg.Text("Interval:"),
        # ToDo: Add combo with all possible interval values
        sg.InputText(size=(4, 1), key="-INTERVAL-", default_text="15m"),
    ],
    [
        sg.Checkbox("RSI", default=False),
        sg.Text("Period:"),
        sg.InputText(size=(3, 1), key="-RSI_PERIOD-", default_text="14"),
        sg.Text("Signal:"),
        sg.Text("Awaiting"),
    ],
]
orders_headings = [
    "Price Level",
    "Symbol",
    "OrderId",
    "Time in Force",
    "Type",
    "Side",
    "Price",
    "Quantity",
    "Status",
]
data = [[]]

list_of_orders = [
    [
        sg.Table(
            values=data,
            headings=orders_headings,
            col_widths=[8, 10, 12, 10, 12, 12, 12, 12, 12],
            auto_size_columns=False,
            justification="center",
            num_rows=10,
            key="-LIST_OF_ORDERS-",
            # display_row_numbers=True,
            row_height=25,
            tooltip="Current list of orders",
            visible=True,
        )
    ]
]
realized_orders = [
    [
        sg.Table(
            values=data,
            headings=orders_headings,
            col_widths=[8, 10, 12, 10, 12, 12, 12, 12, 12],
            auto_size_columns=False,
            justification="center",
            num_rows=10,
            key="-REALIZED_ORDERS-",
            # display_row_numbers=True,
            row_height=25,
            tooltip="Realized orders",
            visible=True,
        )
    ]
]

logger = [
    [
        sg.Output(size=(400, 50), key="-LOGGER-"),
    ]
]

tab_orders = sg.Tab("List of orders", list_of_orders, key="-TAB_ORDERS-")

tab_realized_orders = sg.Tab(
    "Realized orders", realized_orders, key="-TAB-REALIZED-ORDERS-"
)

tab_logger = sg.Tab("Logger", logger, key="-TAB_LOGGER-")
