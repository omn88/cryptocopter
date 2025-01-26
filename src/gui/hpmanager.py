import asyncio
from datetime import datetime
import os
import queue
import logging
from typing import Dict, List
from kivy.properties import (
    ListProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.boxlayout import BoxLayout
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, Mode, PositionSide
from src.common.identifiers.spot import (
    HPConfig,
    HpNew,
    AllTickers,
    Event,
    EventName,
    LoadConfig,
    RemoveRecord,
    SaveConfig,
    SellConfig,
    State,
    StateInfo,
    UiState,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import (
    ActivePosition,
    ArchivedPosition,
    HPUpdate,
    IdlePosition,
    PositionData,
)
from src.gui.searchable_drop_down import SearchableDropDown


logger = logging.getLogger("HP_GUI")


class HpManager(BoxLayout):
    hp_list_data: List[Dict] = ListProperty([])
    active_records: List[Dict] = ListProperty([])
    idle_records: List[Dict] = ListProperty([])
    archive_records: List[Dict] = ListProperty([])
    filtered_active_records: List[Dict] = ListProperty([])
    filtered_idle_records: List[Dict] = ListProperty([])
    filtered_archive_records: List[Dict] = ListProperty([])
    active_filter = StringProperty("All")
    idle_filter = StringProperty("All")
    archive_filter = StringProperty("All")

    log_display = ObjectProperty(None)
    file_name_input = ObjectProperty(None)
    symbols = ListProperty()

    config_dir = os.path.join("src", "strategies", "spot")

    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        strategy_id: str,
        config_queue: queue.Queue,
        ui_queue: queue.Queue,
        symbols_info: Dict[str, SymbolInfo],
        db: Database,
        test_mode=False,  # Add a test_mode parameter
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.symbols_info = symbols_info
        self.client = client
        self.strategy_id = strategy_id
        self.ui_queue = ui_queue
        self.strategy_logger = strategy_logger
        self.config_queue = config_queue
        self.db = db
        self.bind(active_records=self.update_active_symbols)
        self.bind(idle_records=self.update_idle_symbols)
        self.bind(archive_records=self.update_archive_symbols)
        self.symbols = [symbol for symbol, info in self.symbols_info.items()]
        # Suppress GUI initialization when in test mode
        if not test_mode:
            # Create the SearchableDropDown instance with the client
            self.symbol_input = SearchableDropDown(
                client=self.client, options=self.symbols
            )
            # Add it to the layout where needed
            self.ids.symbol_container.add_widget(self.symbol_input)

        # Do not start async tasks in the constructor
        self.is_tasks_initialized = False

    def initialize_tasks(self):
        # Separate method to start async tasks
        if not self.is_tasks_initialized:
            asyncio.create_task(self.update_ui())
            asyncio.create_task(self.refresh_ui())
            self.is_tasks_initialized = True

    def trigger_add_record(self, *args) -> None:
        if not self._validate_buy_inputs():
            return

        new_hp = HpNew(
            config=HPConfig(
                symbol_info=self.symbols_info[self.symbol_input.selected_value],
                price_low=float(self.symbol_input.price_low_input.text),
                price_high=float(self.symbol_input.price_high_input.text),
                budget=float(self.ids.budget_input.text),
                order_trigger=float(self.ids.order_trigger_input.text),
                mode=Mode.DCA
                if self.ids.mode_input.text == Mode.DCA.value
                else Mode.SINGLE,
            ),
            state_info=StateInfo(),
        )
        self.config_queue.put_nowait(new_hp)
        logger.info("New HP added to the queue: %s", new_hp)

    def update_hp_list(self, update: HPUpdate, hp_list: List[Dict]) -> List[Dict]:
        logger.info("Entering update hp list")

        list_of_hp_ids = [int(item["hp_id"]) for item in hp_list]
        logger.info("List of HP IDs: %s", list_of_hp_ids)

        logger.info("update: %s", update)

        if int(update.hp_id) not in list_of_hp_ids:
            hp_record = {
                "hp_manager": self,
                "hp_id": str(update.hp_id),
                "asset": str(update.asset),
                "buy_price": str(update.buy_price)
                if update.buy_price is not None
                else "0.0",
                "quantity": str(update.quantity)
                if update.quantity is not None
                else "0.0",
                "quantity_usdt": str(update.quantity_usdt)
                if update.quantity_usdt is not None
                else "0.0",
                "sell_price": str(update.sell_price)
                if update.sell_price is not None
                else "0.0",
                "expected_return": str(update.expected_return)
                if update.expected_return is not None
                else "0.0",
                "current_price": str(update.current_price)
                if update.current_price is not None
                else "0.0",  # Include current price
                "net": str(update.net)
                if update.net is not None
                else "0.0",  # Include net value
                "net_percent": str(update.net_percent)
                if update.net_percent is not None
                else "0.0",  # Include net percentage
                "state": str(update.state.value),  # Include the state of the position
            }

            hp_list.append(hp_record)
            logger.info("Added new HP %s to %s", hp_record, hp_list)
        else:
            logger.info("HP is already in the list, time to update")
            for index, hp in enumerate(hp_list):
                logger.info("Checking item %s, %s", index, hp)
                if str(hp["hp_id"]) == str(update.hp_id):
                    logger.info(
                        "Found a match with hp id: %s, quantity: %s",
                        update.hp_id,
                        update.quantity,
                    )
                    # Update hp fields
                    if update.buy_price is not None:
                        hp["buy_price"] = str(update.buy_price)
                    if update.quantity is not None:
                        hp["quantity"] = str(
                            self.symbols_info[f"{hp['asset']}USDT"].adjust_quantity(
                                float(hp["quantity"]) + update.quantity
                            )
                        )
                    if update.sell_price is not None:
                        hp["sell_price"] = str(update.sell_price)
                    if update.expected_return is not None:
                        hp["expected_return"] = str(update.expected_return)
                    if update.state.value:
                        hp["state"] = str(
                            update.state.value
                        )  # Include the state of the position

                    hp["quantity_usdt"] = str(
                        self.symbols_info[f"{hp['asset']}USDT"].adjust_price(
                            float(hp["buy_price"]) * float(hp["quantity"])
                        )
                    )

                    logger.info(
                        "Buy price: %s, Quantity: %s, total: %s",
                        hp["buy_price"],
                        hp["quantity"],
                        hp["quantity_usdt"],
                    )

                    # Check if state is CLOSED and quantity is 0, then remove it by index
                    # if (
                    #     hp["state"] == State.CLOSED.value
                    #     and float(hp["quantity"]) == 0.0
                    # ):
                    #     logger.info("State closed, removing item with index %s", index)
                    #     hp_list.pop(index)
                    break  # Exit the loop once the correct item is found and processed

        # Find the updated record and send it to the DB
        updated_hp = next(
            (hp for hp in hp_list if hp["hp_id"] == str(update.hp_id)), None
        )
        if updated_hp:
            self.db.run_db_task(coro=self.db.upsert_hp_record(updated_hp))
            logger.info("Sent updated HP record to DB: %s", updated_hp)

        return hp_list

    async def update_ui(self) -> None:
        logger.info("Ready to receive UI updates")
        while True:
            try:
                data = self.ui_queue.get_nowait()

                if isinstance(data, Event) and data.name == EventName.SENTINEL:
                    logger.info("Received sentinel event, exiting")
                    return

                if isinstance(data, HPUpdate):
                    logger.info("Received HP Update: %s", data)

                    self.hp_list_data = self.update_hp_list(
                        update=data, hp_list=self.hp_list_data
                    )

                    # Refresh the RecycleView or ListView in the UI to reflect new data
                    self.ids.hp_list.refresh_from_data()

                if isinstance(data, PositionData):
                    logger.info("Received position data: %s", data)
                    self.hp_list_data = self.update_hp_list(
                        update=data.hp_update, hp_list=self.hp_list_data
                    )
                    if any(
                        record["hp_id"] == str(data.config.hp_id)
                        for record in self.active_records
                    ):
                        logger.info(
                            "Record %s found in active records", str(data.config.hp_id)
                        )
                        self.update_active_position(data=data)

                    elif any(
                        record["hp_id"] == str(data.config.hp_id)
                        for record in self.idle_records
                    ):
                        logger.info(
                            "Record %s found in idle records", str(data.config.hp_id)
                        )
                        self.update_idle_position(data=data)
                    else:
                        if data.state_info.ui_state in [
                            UiState.NEW,
                            UiState.STAGNATED,
                            None,
                        ]:
                            logger.info(
                                "New position added to Idle, system id: %s",
                                str(data.config.hp_id),
                            )
                            self.add_new_position_to_idle(data=data)
                        if data.state_info.ui_state == UiState.OPEN:
                            logger.info(
                                "New position added to Active, system id: %s",
                                str(data.config.hp_id),
                            )
                            self.add_new_position_to_active(data=data)
                            # if data.recovering:
                    #     if data.ui_state == UiState.OPEN:
                    #         logger.info(
                    #             "Recovering position to active tab in GUI: %s", data
                    #         )
                    #         self.recovery_to_active(data=data)
                    #     if data.ui_state == UiState.NEW:
                    #         logger.info(
                    #             "Recovering position to idle tab in GUI: %s", data
                    #         )
                    #         self.recovery_to_idle(data=data)
                    logger.info(
                        "Records active:\n%s\nIdle\n%s\nArchive\n%s",
                        self.active_records,
                        self.idle_records,
                        self.archive_records,
                    )
                    logger.info("HP LIST: %s", self.hp_list_data)

                if isinstance(data, Event) and data.name == EventName.ALL_TICKERS:
                    for strategy in self.active_records:
                        assert isinstance(data.content, AllTickers)
                        for ticker in data.content.msg:
                            symbol = ticker.get("s")
                            if symbol == strategy["symbol"]:
                                strategy["current_price"] = str(
                                    self.symbols_info[symbol].adjust_price(
                                        price=float(ticker["c"])
                                    )
                                )

                    for strategy in self.idle_records:
                        assert isinstance(data.content, AllTickers)
                        for ticker in data.content.msg:
                            symbol = ticker.get("s")
                            if symbol == strategy["symbol"]:
                                strategy["current_price"] = str(
                                    self.symbols_info[symbol].adjust_price(
                                        price=float(ticker["c"])
                                    )
                                )

                    for strategy in self.hp_list_data:
                        assert isinstance(data.content, AllTickers)
                        for ticker in data.content.msg:
                            symbol = ticker.get("s")
                            if strategy["state"] not in ["CLOSED", "SOLD"]:
                                if symbol == f"{strategy['asset']}USDT":
                                    current_price = self.symbols_info[
                                        symbol
                                    ].adjust_price(price=float(ticker["c"]))
                                    strategy["current_price"] = str(current_price)

                                    if float(strategy["buy_price"]):
                                        net_percent = round(
                                            100
                                            * (
                                                current_price
                                                / float(strategy["buy_price"])
                                                - 1
                                            ),
                                            2,
                                        )
                                        strategy["quantity_usdt"]
                                        net = round(
                                            1
                                            + (net_percent / 100)
                                            * float(strategy["quantity_usdt"]),
                                            2,
                                        )
                                        strategy["net"] = str(net)
                                        strategy["net_percent"] = str(net_percent)
                                    self.ids.hp_list.refresh_from_data()
            except queue.Empty:
                await asyncio.sleep(0.1)

    def update_label(self, instance, value) -> None:
        self.selected_label.text = value

    def update_active_symbols(self, *args) -> None:
        symbols = {"All"}
        for record in self.active_records:
            symbols.add(record.get("symbol", ""))
        self.ids.active_filter_input.values = sorted(list(symbols))

    def update_idle_symbols(self, *args) -> None:
        symbols = {"All"}
        for record in self.idle_records:
            symbols.add(record.get("symbol", ""))
        self.ids.idle_filter_input.values = sorted(list(symbols))

    def update_archive_symbols(self, *args) -> None:
        symbols = {"All"}
        for record in self.archive_records:
            symbols.add(record.get("symbol", ""))
        self.ids.archive_filter_input.values = sorted(list(symbols))

    def validate_sell_inputs(self) -> bool:
        hp_id = self.ids.hp_id_input.text
        sell_price = self.ids.sell_price_input.text
        total_usdt = self.ids.total_usdt_value_label.text

        validation_message = ""
        if not hp_id:
            validation_message += "HP ID is required. "
        if not sell_price:
            validation_message += "Sell price is required. "
        if not total_usdt:
            validation_message += "Total USDT price is required. "

        self.ids.sell_validation_label.text = validation_message

        return not validation_message

    def set_sell_price(self, *args) -> None:
        if not self.validate_sell_inputs():
            return

        sell_config = SellConfig(
            config=HPConfig(
                hp_id=self.ids.hp_id_input.text,
                symbol_info=self.symbols_info[f"{self.ids.asset_label.text}USDT"],
                price_low=float(self.ids.sell_price_input.text),
                price_high=float(self.ids.sell_price_input.text),
                budget=float(self.ids.quantity_label.text),
                order_trigger=1.0,
                mode=Mode.SINGLE,
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.config_queue.put_nowait(sell_config)
        logger.info("Sell config added to the queue: %s", sell_config.config)

        self.filter_records(tab="idle", symbol_filter="All")

    def trigger_remove_record(
        self,
        hp_id,
        symbol,
        side,
        *args,
    ) -> None:
        record = RemoveRecord(hp_id=hp_id, symbol=symbol, side=side)
        self.config_queue.put_nowait(record)
        logger.info("Remove record added to the queue. %s", record)

    def save_config(self) -> None:
        file_name = self.file_name_input.text.strip()
        if not file_name:
            # Provide feedback to the user if the file name is empty
            print("Please enter a file name.")
            return

        # Put the SaveConfig NamedTuple into the config_queue
        self.config_queue.put(SaveConfig(file_name=file_name))
        logger.info("Saving configuration request for %s sent to backend.", file_name)

    def load_config(self) -> None:
        file_name = self.file_name_input.text.strip()
        if not file_name:
            # Provide feedback to the user if the file name is empty
            print("Please enter a file name.")
            return

        # Put the LoadConfig NamedTuple into the config_queue
        self.config_queue.put(LoadConfig(file_name=file_name))
        logger.info("Loading configuration request for %s sent to backend.", file_name)

    def sell_hp(self, hp_id, asset, quantity, buy_price):
        """
        Moves to the Sell tab and fills the HP data (HP ID, asset, quantity).

        Args:
        - hp_id: The ID of the HP to sell.
        - asset: The asset involved in the HP.
        - quantity: The amount of the asset to sell.
        """
        # Move to the "Sell" tab
        self.ids.hp_tabbed_panel.switch_to(
            self.ids.hp_sell_tab
        )  # Assuming 'sell_tab' is the ID for the "Sell" tab.

        # Populate the fields in the Sell tab
        self.ids.hp_id_input.text = str(hp_id)
        self.ids.asset_label.text = str(asset)
        self.ids.quantity_label.text = str(quantity)
        self.ids.quantity_usdt_label.text = str(
            round(float(quantity) * float(buy_price), 2)
        )
        self.ids.buy_price_label.text = str(buy_price)

        # Clear or reset the sell price field
        self.ids.sell_price_input.text = ""

        # Optional: If you want to set focus on the sell price input field
        self.ids.sell_price_input.focus = True

        logger.info(
            "Moved to 'Sell' tab for HP ID: %s, Asset: %s, Quantity: %s",
            hp_id,
            asset,
            quantity,
        )

    def calculate_expected_gain(self, sell_price):
        """
        Calculate the expected gain and gain percentage based on the sell price.

        Args:
        - sell_price: The entered sell price.
        """
        try:
            sell_price_float = float(sell_price)
            quantity_float = float(self.ids.quantity_label.text)
            quantity_usdt_float = float(self.ids.quantity_usdt_label.text)
            buy_price_float = float(self.ids.buy_price_label.text)

            # Total USDT value calculation
            total_usdt_value = sell_price_float * quantity_float

            # Expected gain calculations
            expected_gain_usdt = total_usdt_value - quantity_usdt_float
            expected_gain_percent = ((sell_price_float / buy_price_float) - 1) * 100

            # Update labels
            self.ids.expected_gain_label.text = f"{expected_gain_usdt:.2f}"
            self.ids.expected_gain_percent_label.text = f"{expected_gain_percent:.2f}%"
            self.ids.total_usdt_value_label.text = f"{total_usdt_value:.2f}"

        except ValueError:
            # Handle potential conversion errors (e.g., if the inputs are not valid floats)
            logger.error("Error in calculating expected gain. Invalid input detected.")
            self.ids.expected_gain_label.text = "---"
            self.ids.expected_gain_percent_label.text = "---"

    def cancel_sell(self, hp_id: str, asset: str):
        config = HPConfig(
            hp_id=hp_id,
            symbol_info=self.symbols_info[f"{asset}USDT"],
            price_low=0.0,
            price_high=0.0,
            budget=0.0,
            order_trigger=1.0,
            mode=Mode.SINGLE,
        )
        state_info = StateInfo(side=PositionSide.SHORT, ui_state=UiState.CLOSED)

        self.config_queue.put_nowait(
            SellConfig(
                config=config,
                state_info=state_info,
            )
        )

        logger.info("Cancel sell send to the config queue: %s", config)

        self.filter_records(tab="idle", symbol_filter="All")
        self.filter_records(tab="active", symbol_filter="All")
        self.filter_records(tab="archive", symbol_filter="All")

    def fetch_hp_info(self, hp_id):
        """
        Fetches and populates the HP information into the Sell tab based on the provided hp_id.
        If hp_id is not found, resets all fields to '---'.

        Args:
        - hp_id: The HP ID entered by the user.
        """
        try:
            for item in self.hp_list_data:
                if int(item["hp_id"]) == int(hp_id):
                    # Populate the fields in the Sell tab
                    self.ids.hp_id_input.text = str(hp_id)
                    self.ids.asset_label.text = item["asset"]
                    self.ids.quantity_label.text = item["quantity"]
                    self.ids.quantity_usdt_label.text = str(
                        round(float(item["quantity"]) * float(item["buy_price"]), 2)
                    )
                    self.ids.buy_price_label.text = item["buy_price"]

                    # Clear or reset the sell price field
                    self.ids.sell_price_input.text = ""  # Clear any previous sell price

                    # Optional: Set focus on the sell price input field
                    self.ids.sell_price_input.focus = True

                    return

            # If hp_id is not found in hp_list_data, raise ValueError to reset fields
            raise ValueError("HP ID not found")

        except ValueError:
            # Reset all fields to '---' if HP ID is not found or any error occurs
            logger.error(f"HP ID {hp_id} not found in hp_list_data, resetting fields.")
            self.ids.asset_label.text = "---"
            self.ids.quantity_label.text = "---"
            self.ids.quantity_usdt_label.text = "---"
            self.ids.buy_price_label.text = "---"
            self.ids.sell_price_input.text = ""  # Optional: Clear any sell price input
            self.ids.expected_gain_label.text = "---"
            self.ids.expected_gain_percent_label.text = "---"
            self.ids.total_usdt_value_label.text = ""

    async def refresh_ui(self):
        while True:
            # Reassign the data to trigger the UI update
            self.ids.buy_active_records_list.refresh_from_data()
            self.ids.sell_active_records_list.refresh_from_data()
            self.ids.buy_idle_records_list.refresh_from_data()
            self.ids.sell_idle_records_list.refresh_from_data()
            self.ids.buy_archive_records_list.refresh_from_data()
            self.ids.sell_archive_records_list.refresh_from_data()
            self.ids.hp_list.refresh_from_data()
            await asyncio.sleep(1)

    def add_new_position_to_idle(self, data: PositionData) -> None:
        trigger_price = data.config.symbol_info.adjust_price(
            (
                (1 + (data.config.order_trigger / 100)) * data.config.price_high
                if data.state_info.side.value == PositionSide.LONG.value
                else (1 - (data.config.order_trigger / 100)) * data.config.price_low
            )
        )

        self.idle_records.append(
            IdlePosition(
                open_time=data.state_info.open_time,
                hp_id=str(data.config.hp_id),
                symbol=data.config.symbol_info.symbol,
                side=str(data.state_info.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_trigger=f"{data.config.order_trigger},({trigger_price})",
                state=str(data.state_info.ui_state),
                completeness=str(data.state_info.completeness),
            ).to_dict()
        )
        self.filter_records("idle", "All")

    def add_new_position_to_active(self, data: PositionData) -> None:
        cancel_price = data.config.symbol_info.adjust_price(
            (
                (1 + (2 * data.config.order_trigger / 100)) * data.config.price_high
                if data.state_info.side.value == PositionSide.LONG.value
                else (1 - (2 * data.config.order_trigger / 100)) * data.config.price_low
            )
        )

        self.active_records.append(
            ActivePosition(
                open_time=data.state_info.open_time,
                hp_id=str(data.config.hp_id),
                symbol=data.config.symbol_info.symbol,
                side=str(data.state_info.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_cancel=f"{2 * data.config.order_trigger},({cancel_price})",
                stagnation=f"{data.state_info.stagnation_counter}/{data.state_info.stagnation_limit}",
                completeness=str(data.state_info.completeness),
                state=str(data.state_info.ui_state),
            ).to_dict()
        )
        self.filter_records("active", "All")

    def add_position_to_archive(self, data: PositionData) -> None:
        data.state_info.close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.archive_records.append(
            ArchivedPosition(
                open_time=data.state_info.open_time,
                close_time=data.state_info.close_time,
                hp_id=str(data.config.hp_id),
                symbol=data.config.symbol_info.symbol,
                side=str(data.state_info.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_trigger=str(data.config.order_trigger),
                completeness=str(data.state_info.completeness),
            ).to_dict()
        )
        self.filter_records("archive", "All")

    def update_active_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.active_records:
            condition = (
                str(position["hp_id"]) == str(data.config.hp_id)
                and position["side"] == data.state_info.side.value
            )
            logger.info(
                "pos hp_id: %s, data config hp_id: %s, pos side: %s, data state info side: %s, condition: %s",
                position["hp_id"],
                data.config.hp_id,
                position["side"],
                data.state_info.side.value,
                condition,
            )
            if (
                str(position["hp_id"]) == str(data.config.hp_id)
                and position["side"] == data.state_info.side.value
            ):
                logger.info(
                    "Going to update active position %s %s",
                    position["hp_id"],
                    position["side"],
                )
                position["stagnation_counter"] = str(data.state_info.stagnation_counter)
                position["stagnation_limit"] = str(data.state_info.stagnation_limit)
                position["completeness"] = str(data.state_info.completeness)
                position["state"] = str(data.state_info.ui_state)

                if data.state_info.ui_state == UiState.CLOSED:
                    data.state_info.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.active_records.remove(position)
                    archived_position = ArchivedPosition(
                        open_time=data.state_info.open_time,
                        close_time=data.state_info.close_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=str(data.config.order_trigger),
                        completeness=str(data.state_info.completeness),
                    )
                    self.archive_records.append(archived_position.to_dict())
                    logger.info("Archiving price level: %s", archived_position)
                    if data.state_info.completeness == 1.0:
                        self.config_queue.put_nowait(
                            RemoveRecord(
                                hp_id=str(data.config.hp_id),
                                symbol=data.config.symbol_info.symbol,
                                side=data.state_info.side.value,
                            )
                        )

                if data.state_info.ui_state == UiState.STAGNATED:
                    trigger_price = data.config.symbol_info.adjust_price(
                        (
                            (1 + (data.config.order_trigger / 100))
                            * data.config.price_high
                            if data.state_info.side.value == PositionSide.LONG.value
                            else (1 - (data.config.order_trigger / 100))
                            * data.config.price_low
                        )
                    )

                    self.active_records.remove(position)
                    idle_position = IdlePosition(
                        open_time=data.state_info.open_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=f"{data.config.order_trigger},({trigger_price})",
                        state=str(data.state_info.ui_state),
                        completeness=str(data.state_info.completeness),
                    )
                    self.idle_records.append(idle_position.to_dict())
                    logger.info("Price level stagnated: %s", idle_position)
        self.filter_records("active", "All")
        self.filter_records("idle", "All")
        self.filter_records("archive", "All")

    def update_idle_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.idle_records:
            if (
                position["hp_id"] == str(data.config.hp_id)
                and position["side"] == data.state_info.side.value
            ):
                logger.info(
                    "Going to update idle position %s %s",
                    position["hp_id"],
                    position["side"],
                )
                position["stagnation_counter"] = str(data.state_info.stagnation_counter)
                position["stagnation_limit"] = str(data.state_info.stagnation_limit)
                position["completeness"] = str(data.state_info.completeness)
                position["state"] = str(data.state_info.ui_state)
                logger.info("Data state: %s", data.state_info.ui_state)
                if data.state_info.ui_state == UiState.OPEN:
                    self.idle_records.remove(position)
                    cancel_price = data.config.symbol_info.adjust_price(
                        (
                            (1 + (2 * data.config.order_trigger / 100))
                            * data.config.price_high
                            if data.state_info.side.value == PositionSide.LONG.value
                            else (1 - (2 * data.config.order_trigger / 100))
                            * data.config.price_low
                        )
                    )
                    active_position = ActivePosition(
                        open_time=data.state_info.open_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_cancel=f"{2 * data.config.order_trigger},({cancel_price})",
                        stagnation=f"{data.state_info.stagnation_counter}/{data.state_info.stagnation_limit}",
                        completeness=str(data.state_info.completeness),
                        state=str(data.state_info.ui_state),
                    )
                    self.active_records.append(active_position.to_dict())
                    logger.info("Activating price level: %s", active_position)
                if data.state_info.ui_state == UiState.CLOSED:
                    data.state_info.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.idle_records.remove(position)
                    archived_position = ArchivedPosition(
                        open_time=data.state_info.open_time,
                        close_time=data.state_info.close_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=str(data.config.order_trigger),
                        completeness=str(data.state_info.completeness),
                    )
                    self.archive_records.append(archived_position.to_dict())
                    logger.info("Archiving price level: %s", archived_position)

        self.filter_records("idle", "All")
        self.filter_records("active", "All")
        self.filter_records("archive", "All")

    def filter_records(self, tab, symbol_filter) -> None:
        if tab == "active":
            self.active_filter = symbol_filter
            self.filtered_active_records = [
                record
                for record in self.active_records
                if symbol_filter == "All" or record["symbol"] == symbol_filter
            ]
        elif tab == "idle":
            self.idle_filter = symbol_filter
            self.filtered_idle_records = [
                record
                for record in self.idle_records
                if symbol_filter == "All" or record["symbol"] == symbol_filter
            ]
        elif tab == "archive":
            self.archive_filter = symbol_filter
            self.filtered_archive_records = [
                record
                for record in self.archive_records
                if symbol_filter == "All" or record["symbol"] == symbol_filter
            ]

        self.ids.buy_active_records_list.refresh_from_data()
        self.ids.sell_active_records_list.refresh_from_data()
        self.ids.buy_idle_records_list.refresh_from_data()
        self.ids.sell_idle_records_list.refresh_from_data()
        self.ids.buy_archive_records_list.refresh_from_data()
        self.ids.sell_archive_records_list.refresh_from_data()

    def _validate_buy_inputs(self) -> bool:
        symbol = self.symbol_input.selected_value
        price_low = self.symbol_input.price_low_input.text
        price_high = self.symbol_input.price_high_input.text
        budget = self.ids.budget_input.text
        order_trigger = self.ids.order_trigger_input.text
        mode = self.ids.mode_input.text

        validation_message = ""
        if not symbol:
            validation_message += "Symbol is required. "
        if not price_low or not price_high:
            validation_message += "Price range is required. "
        if not budget:
            validation_message += "Budget is required. "
        if not order_trigger:
            validation_message += "Order trigger is required. "
        if mode not in [Mode.DCA.value, Mode.SINGLE.value]:
            validation_message += "Mode has to be selected."
        if price_low > price_high:
            validation_message += "Price low is bigger than price high. "

        self.ids.buy_validation_label.text = validation_message

        return not validation_message
