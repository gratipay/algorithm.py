#!/bin/sh -eu
python algorithm.py
py.test -v tests.py
pyflakes algorithm.py tests.py
