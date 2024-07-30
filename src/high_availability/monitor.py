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
            proc.name(),
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None, None, None, None


def start_process(script):
    process = subprocess.Popen(
        ["python", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    pid = process.pid
    create_time = datetime.datetime.fromtimestamp(psutil.Process(pid).create_time())
    name = psutil.Process(pid).name()
    logger.info("Started process '%s' with PID: %d", script, pid)
    return pid, create_time, name


async def monitor_process(
    pid,
    script,
    original_create_time,
    original_name,
    interval=10,
    max_retries=3,
    retry_delay=5,
):
    retries = 0
    while True:
        pid, status, create_time, name = get_process_info(pid)
        if (
            pid
            and status == psutil.STATUS_RUNNING
            and create_time == original_create_time
            and name == original_name
        ):
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
                if pid is None:
                    logger.warning(
                        "Process PID is None. Retrying %d/%d...", retries, max_retries
                    )
                else:
                    logger.warning(
                        "Process %d is not running or mismatched (status: %s, name: %s). Retrying %d/%d...",
                        pid,
                        status,
                        name,
                        retries,
                        max_retries,
                    )
                await asyncio.sleep(retry_delay)
            else:
                if pid is None:
                    logger.error(
                        "Process PID is None after %d retries. Restarting...", retries
                    )
                else:
                    logger.error(
                        "Process %d failed or mismatched after %d retries. Restarting...",
                        pid,
                        retries,
                    )
                pid, create_time, name = start_process(script)
                original_create_time = create_time
                original_name = name
                retries = 0
                logger.info("Restarted process '%s' with PID: %d", script, pid)

        await asyncio.sleep(interval)


async def main():
    script = "main.py"  # Replace with the path to your script
    pid, create_time, name = start_process(script)
    await monitor_process(pid, script, create_time, name)


if __name__ == "__main__":
    asyncio.run(main())
