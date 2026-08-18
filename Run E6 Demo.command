#!/bin/zsh
set -e
script_directory=${0:A:h}
cd "$script_directory"
PYTHONPATH=src exec /usr/bin/python3 -m pitrac_easy_connect.demo e6

