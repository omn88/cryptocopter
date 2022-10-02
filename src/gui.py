import asyncio
import logging
import PySimpleGUI as sg
import gui_elements as elem
from log import Handler


logger = logging.getLogger("gui")

layout = [
    [
        sg.Frame(title="", layout=elem.user_input, key="-USER_INPUT-"),
        sg.Column(elem.user_input_control, key="-USER_INPUT_CONTROL-"),
    ],
    [sg.Frame(title="Indicators", layout=elem.indicators, key="-INDICATORS-")],
    [
        sg.TabGroup(
            [
                [
                    elem.tab_position,
                    elem.tab_open_orders,
                    elem.tab_realized_orders,
                    elem.tab_logger,
                ]
            ],
            size=(2840, 2340),
            key="-TAB_GROUP-",
            tab_location="topleft",
            pad=(0, 0),
        )
    ],
]

# server_time = await client.get_server_time()
window = sg.Window(
    title="Cryptocopter",
    layout=layout,
    location=(250, 200),
    size=(880, 400),
    resizable=True,
    finalize=True,
)

ch = Handler(window)
ch.setLevel(logging.INFO)
logger.addHandler(ch)
logger.info("Strategy and window created")


async def gui():
    # Event Loop to process "events" and get the "values" of the inputs
    while True:
        event, values = window.read(timeout=100)
        # print(f"Event: {event}, values: {values}")
        if event in (sg.WIN_CLOSED, "-EXIT_STRATEGY-"):
            logger.info("Exit")
            break
