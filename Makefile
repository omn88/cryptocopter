# Separator is a \tab
.venv:
	@echo "Virtual env does not exist"
	python3 -m venv .venv
	python3 -m pip install -r requirements.txt


ut: | .venv
	pytest tests
