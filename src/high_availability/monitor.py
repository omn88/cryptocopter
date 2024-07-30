import subprocess
import asyncio
import datetime
import psutil

from logger_config import logger


def get_process_info(pid):
    try:
        proc = psutil.Process(pid)
        return (
            proc.pid,
            proc.status(),
            datetime.datetime.fromtimestamp(proc.create_time()),
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None, None, None


def start_process(script):
    process = subprocess.Popen(['python', script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pid = process.pid
    logger.info("Started process '%s' with PID: %d", script, pid)
    return pid


async def monitor_process(pid, script, interval=10, max_retries=3, retry_delay=5):
    retries = 0
    while True:
        pid, status, create_time = get_process_info(pid)
        if pid and status == psutil.STATUS_RUNNING:
            logger.info(
                "Process %d is running, status: %s, started at: %s",
                pid,
                status,
                create_time,
            )
            retries = 0  # Reset retries on successful check
        else:
            if retries < max_retries:
                retries += 1
                logger.warning(
                    "Process %d is not running (status: %s). Retrying %d/%d...",
                    pid,
                    status,
                    retries,
                    max_retries,
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.error(
                    "Process %d failed after %d retries. Restarting...", pid, retries
                )
                pid = start_process(script)
                retries = 0
                logger.info("Restarted process '%s' with PID: %d", script, pid)

        await asyncio.sleep(interval)


async def main():
    script = "main.py"  # Replace with the path to your script
    pid = start_process(script)
    await monitor_process(pid, script)


if __name__ == "__main__":
    asyncio.run(main())
