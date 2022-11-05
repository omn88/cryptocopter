import logging

logger = logging.getLogger("worker")


async def worker(queue):
    while True:
        # Get a "work item" out of the queue.
        task = await queue.get()

        # Sleep for the "sleep_for" seconds.
        logger.info("Task %s" % task)

        # Notify the queue that the "work item" has been processed.
        queue.task_done()
