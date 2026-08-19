#!/bin/zsh
# Double-click this to try Easy Connect against your own PiTrac enclosure.
set -e
cd "${0:A:h}"
clear
PYTHONPATH=src exec /usr/bin/python3 -m pitrac_easy_connect.tryit gspro
