# Separator is a \tab
SHELL=/bin/bash

VIRTUALENV_PATH=.venv
PYTHON=${VIRTUALENV_PATH}/bin/python

prepare_venv:
	@echo "Virtual env does not exist"
	python3 -m venv ${VIRTUALENV_PATH}
	${PYTHON} -m pip install -r requirements.txt

clean_pyc:
	find . -not -path ".venv/*" -name "*.pyc" -exec rm -f {} \;
	find . -type d -name "__pycache__" -exec rm -rf {} +;
	find . -type d -name ".pytest_cache" -exec rm -rf {} +;

clean_venv:
	rm -rf ${VIRTUALENV_PATH}
	find . -type d -name "__pycache__" -exec rm -rf {} +;

ut:
	${PYTHON} -m pytest tests -vvv
