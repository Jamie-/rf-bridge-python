.DEFAULT_GOAL := run
.PHONY: clean, depends, venv, reset

clean: # Clean build files
	rm -f **/*.pyc
	rm -rf **/__pycache__/

depends: # Install all dependancies into `lib`
	venv/bin/pip install -r requirements.txt

venv: # Create virtual environment
	python3 -m venv venv
	venv/bin/pip install -r requirements.txt

reset: # Delete venv
	rm -rf venv
