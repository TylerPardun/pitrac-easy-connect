#!/bin/zsh
# Double-click to try the whole thing with no hardware at all:
# a stand-in simulator, a simulated Raspberry Pi, and the real app.
set -e
cd "$(dirname "$0")"
clear
PYTHONPATH=src exec /usr/bin/python3 -m pitrac_easy_connect.demo gspro
