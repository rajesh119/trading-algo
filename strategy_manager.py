import multiprocessing
import yaml
import os
from strategy.survivor import SurvivorStrategy
from brokers import BrokerGateway
from dispatcher import DataDispatcher
from orders import OrderTracker
from logger import logger
from queue import Queue
import time

def run_strategy(config, log_queue):
    """
    This function will be run in a separate process.
    """
    try:
        broker = BrokerGateway.from_name(os.getenv("BROKER_NAME"))
        order_tracker = OrderTracker()

        try:
            instrument_token = config['index_symbol']
            logger.info(f"✓ Index instrument token obtained: {instrument_token}")
        except Exception as e:
            logger.error(f"Failed to get instrument token for {config['index_symbol']}: {e}")
            return

        dispatcher = DataDispatcher()
        dispatcher.register_main_queue(Queue())

        def on_ticks(ws, ticks):
            if isinstance(ticks, list):
                dispatcher.dispatch(ticks)
            else:
                if "symbol" in ticks:
                    dispatcher.dispatch(ticks)

        def on_connect(ws, response):
            broker.symbols_to_subscribe([instrument_token])

        def on_order_update(ws, data):
            log_queue.put(f"Order update received: {data}")

        broker.connect_websocket(on_ticks=on_ticks, on_connect=on_connect)
        broker.connect_order_websocket(on_order_update=on_order_update)
        time.sleep(10)

        strategy = SurvivorStrategy(broker, config, order_tracker)

        while True:
            try:
                tick_data = dispatcher._main_queue.get()
                if isinstance(tick_data, list):
                    symbol_data = tick_data[0]
                else:
                    symbol_data = tick_data

                if isinstance(symbol_data, dict) and ('last_price' in symbol_data or 'ltp' in symbol_data):
                    strategy.on_ticks_update(symbol_data)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log_queue.put(f"Error in strategy loop: {e}")

    except Exception as e:
        log_queue.put(f"Error initializing strategy: {e}")


class StrategyManager:
    def __init__(self):
        self.process = None
        self.log_queue = multiprocessing.Queue()

    def start(self, config_overrides=None):
        if self.process and self.process.is_alive():
            return "Strategy is already running."

        config_file = os.path.join(os.path.dirname(__file__), "strategy/configs/survivor.yml")
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)['default']

        if config_overrides:
            config.update(config_overrides)

        self.process = multiprocessing.Process(target=run_strategy, args=(config, self.log_queue))
        self.process.start()
        return "Strategy started."

    def stop(self):
        if not self.process or not self.process.is_alive():
            return "Strategy is not running."

        self.process.terminate()
        self.process.join()
        return "Strategy stopped."

    def get_status(self):
        if self.process and self.process.is_alive():
            return "Running"
        return "Stopped"

    def get_logs(self):
        logs = []
        while not self.log_queue.empty():
            logs.append(self.log_queue.get())
        return logs

if __name__ == '__main__':
    manager = StrategyManager()
    manager.start()
    time.sleep(60)
    manager.stop()
