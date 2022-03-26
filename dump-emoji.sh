#!/usr/bin/bash

mkdir -p log .slack-emoji
if [[ ! -f emoji.json ]] ; then  # @TODO request neccessary permissions for app and automate
    echo "API repsonse dump 'emoji.json' not found"
    echo "1. Fetch all data from this endpoint: https://api.slack.com/methods/emoji.list/"
    echo "2. Save it as 'emoji.json' (use 'emoji.example.json' as a reference)"
    exit 1
fi
export PYTHONPATH="$PWD"
venv/bin/python pyslacker/emoji_dumper.py emoji.json .slack-emoji
