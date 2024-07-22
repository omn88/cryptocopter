import asyncio
from datetime import datetime
import os
import logging
import subprocess
import time
import logging
from multiprocessing import Queue, Process
import aiomysql
from decouple import Config, RepositoryEnv
os.environ["KIVY_LOG_MODE"] = "MIXED"
HEARTBEAT_TIMEOUT = 60

DB_CONFIG_FILE = "config/.db_config"
config_db = Config(RepositoryEnv(DB_CONFIG_FILE))


class HealthCheckFailedException(Exception):
    """Exception raised when health check fails for the application or MySQL."""




CHECK_INTERVAL = 5  # Time in seconds to wait between checks
TIMEOUT_THRESHOLD = 10  # Time in seconds to wait before considering the application unresponsive

logging.basicConfig(level=logging.DEBUG)

def start_application(queue: Queue):
    process = subprocess.Popen(
        ['python', 'main.py'],
        env={**os.environ, 'QUEUE_FD': str(queue._reader.fileno())},
        pass_fds=(queue._reader.fileno(),)
    )
    return process

def is_process_alive(process):
    return process.poll() is None

def monitor_application(queue):
    last_update_time = time.time()
    while True:
        try:
            message = queue.get_nowait()
            if message == "alive":
                last_update_time = time.time()
            elif message.startswith("error"):
                logging.error("Received error from main application: %s", message)
        except:
            pass

        if time.time() - last_update_time > TIMEOUT_THRESHOLD:
            logging.error("No status update from the application. Restarting...")
            return False

        time.sleep(CHECK_INTERVAL)
        return True


async def check_mysql_status():
    pool = None
    try:
        pool = await aiomysql.create_pool(
            host=config_db("DB_HOST"),
            port=int(config_db("DB_PORT")),
            user=config_db("DB_USER"),
            password=config_db("DB_PASSWORD"),
            db=config_db("DB_NAME"),
        )
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                result = await cur.fetchone()
                if result:
                    logging.debug("MySQL status: OK")
                    return True
    except aiomysql.OperationalError as err:
        logging.error("MySQL Operational Error: %s", err)
    except aiomysql.InternalError as err:
        logging.error("MySQL Internal Error: %s", err)
    except aiomysql.InterfaceError as err:
        logging.error("MySQL Interface Error: %s", err)
    except aiomysql.Error as err:
        logging.error("MySQL Error: %s", err)
    except Exception as err:
        logging.error("Unexpected error: %s", err)
    finally:
        if pool:
            pool.close()
            await pool.wait_closed()
    return False


async def start_mysql():
    # Start MySQL as a Windows service
    await asyncio.create_subprocess_exec("net", "start", "MySQL80")


# async def monitor_application():
#     process = asyncio.create_task(main())
#     mysql_healthy = await check_mysql_status()

#     while True:
#         try:
#             healthy_app = await check_heartbeat()
#             if healthy_app and mysql_healthy:
#                 logging.info(
#                     "Initialization complete. Application and MySQL are HEALTHY."
#                 )
#                 break
#             raise HealthCheckFailedException("Application or MySQL is not healthy.")
#         except HealthCheckFailedException as e:
#             logging.error("Initialization error: %s. Retrying in 5 seconds...", e)
#             await asyncio.sleep(5)

#     last_healthy_app = healthy_app
#     last_healthy_mysql = mysql_healthy

#     while True:
#         healthy_app = await check_heartbeat()
#         healthy_mysql = await check_mysql_status()

#         if healthy_app != last_healthy_app:
#             if healthy_app:
#                 logging.info("Application status changed: HEALTHY.")
#             else:
#                 logging.info("Application status changed: UNHEALTHY. Restarting...")
#                 process.terminate()
#                 await process.wait()
#                 process = asyncio.create_task(main())
#             last_healthy_app = healthy_app

#         if healthy_mysql != last_healthy_mysql:
#             if healthy_mysql:
#                 logging.info("MySQL status changed: HEALTHY.")
#             else:
#                 logging.info("MySQL status changed: UNHEALTHY. Restarting...")
#                 await start_mysql()
#             last_healthy_mysql = healthy_mysql

#         await asyncio.sleep(5)  # Check every 5 seconds


def setup_logging():
    # Ensure the log directory exists
    log_dir = "artifacts/high_availability"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Generate the log filename with the current timestamp
    log_filename = datetime.now().strftime(
        os.path.join(log_dir, "monitor_%Y%m%d_%H%M%S.log")
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Setup basic config for file logging with UTF-8 encoding
    logging.basicConfig(
        filename=log_filename,
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        encoding="utf-8",  # Ensure UTF-8 encoding
    )

    # Adding a console handler for debugging
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logging.getLogger().addHandler(console_handler)


if __name__ == "__main__":
    setup_logging()
    logging.info("Starting the monitor application.")  # Initial log message to verify
    queue = Queue()
    app_process = start_application(queue)
    try:
        while True:
            if not is_process_alive(app_process) or not monitor_application(queue):
                logging.error("Application process has terminated or is unresponsive. Restarting...")
                app_process.terminate()
                app_process.wait()
                app_process = start_application(queue)
    except KeyboardInterrupt:
        app_process.terminate()
        app_process.wait()
