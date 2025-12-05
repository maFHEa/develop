#!/bin/bash
# OpenFHE test runner with automatic environment setup

cd "$(dirname "$0")"
source venv/bin/activate
python test_threshold_mult.py
