import logging

buffer = ""


class Handler(logging.StreamHandler):
    def __init__(self, window):
        logging.StreamHandler.__init__(self)
        self.window = window

    def emit(self, record):
        global buffer
        record = f"{record.name}, [{record.levelname}], {record.message}"
        buffer = f"{buffer}\n{record}".strip()
        self.window["-LOGGER-"].update(value=buffer)
