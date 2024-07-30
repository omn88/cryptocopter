import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Generate a timestamp for the log filename
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# Configure the logger for the process monitor
logger = logging.getLogger('process_monitor')
logger.setLevel(logging.INFO)

# Create a file handler for logging with timestamp in filename
log_filename = f'artifacts/high_availability/process_monitor_{timestamp}.log'
file_handler = RotatingFileHandler(log_filename, maxBytes=5*1024*1024, backupCount=2)
file_handler.setLevel(logging.INFO)

# Create a console handler for logging
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create a formatter and set it for both handlers
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)
