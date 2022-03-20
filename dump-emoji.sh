#!/usr/bin/bash

mkdir -p log .slack-emoji
export PYTHONPATH="$PWD"
venv/bin/python pyslacker/emoji_dumper.py emoji.json .slack-emoji
