# Separator is a \tab
SHELL=/bin/bash

VIRTUALENV_PATH=.venv

prepare_venv:
	@echo "Virtual env does not exist"
	python3 -m venv ${VIRTUALENV_PATH}
	python3 -m pip install -r requirements.txt

# Figure out how to pass to session where the Makefile is run
activate_venv:
	source ${VIRTUALENV_PATH}/bin/activate
	pip list

deactivate_venv:
	deactivate

clean_venv:
	rm -rf ${VIRTUALENV_PATH}

# Here 
# clean_pyc:
# 	find . -not -path ".venv/*" -name "*.pyc" -exec rm -f {} \;
# 	find . -not -path ".venv/*" -name "__pycache__" -exec rm -f {} \;
# 	find . .-not -path ".venv/*" -name ".pytest_cache" -exec rm -f {} \;

ut: | prepare_venv
	pytest tests
