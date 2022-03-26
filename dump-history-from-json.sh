#!/usr/bin/bash

mkdir -p log
[[ ! -f channel.json ]] && echo "Channel list 'channel.json' not found" && exit 1
venv/bin/python -m pyslacker -cr --ch channel.json
