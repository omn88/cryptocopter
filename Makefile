# Separator is a \tab
SHELL=/bin/bash

VIRTUALENV_PATH=.venv
PYTHON=${VIRTUALENV_PATH}/bin/python

prepare_prod_venv:
	@echo "Virtual env does not exist"
	python3 -m venv ${VIRTUALENV_PATH}

prod_venv: prepare_prod_venv
	${PYTHON} -m pip install -r requirements/production.txt

develop_venv: prepare_prod_venv
	${PYTHON} -m pip install -r requirements/develop.txt

clean_pyc:
	find . -not -path ".venv/*" -name "*.pyc" -exec rm -f {} \;
	find . -not -path ".venv/*" -type d -name "__pycache__" -exec rm -rf {} +;
	find . -not -path ".venv/*" -type d -name ".pytest_cache" -exec rm -rf {} +;

clean_venv:
	rm -rf ${VIRTUALENV_PATH}
	find . -type d -name "__pycache__" -exec rm -rf {} +;

ut:
	${PYTHON} -m pytest tests -vvv

sanity:
	${PYTHON} -m pytest tests -m "not db" --override-ini="addopts=" -q

db-tests:
	${PYTHON} -m pytest tests -m "db" --override-ini="addopts=" -q
