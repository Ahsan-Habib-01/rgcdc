#!/usr/bin/env bash
set -e
echo "=========================================================="
echo " RGCDC Debate Tabulation System - PythonAnywhere Installer"
echo "=========================================================="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python3 backend/test_algorithm.py
echo "=========================================================="
echo " SUCCESS! Environment & Database Ready!"
echo " Next: In PythonAnywhere -> Web Tab -> WSGI configuration,"
echo " point application to: $(pwd)/wsgi.py and click Reload!"
echo "=========================================================="
