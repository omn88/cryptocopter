# Separator is a \tab
SHELL=/bin/bash

VIRTUALENV_PATH=.venv
PYTHON=${VIRTUALENV_PATH}/bin/python

prepare_venv:
	@echo "Virtual env does not exist"
	python3 -m venv ${VIRTUALENV_PATH}
	${PYTHON} -m pip install -r requirements.txt

clean_venv:
	rm -rf ${VIRTUALENV_PATH}

ut:
	${PYTHON} -m pytest tests -vvv
