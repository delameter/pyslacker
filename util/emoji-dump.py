#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# script for batch emoji download
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
# SEMI-MANUAL MODE ONLY
# 1. Fetch thw result from this endpoint: https://api.slack.com/methods/emoji.list/
# 2. Save it to a file (.json)
# 3. Activate venv: source venv/bin/activate
# 4. Launch this script, it takes two args; first is path to json-file, second is output dir
#    Example: ./util/emoji-dump.py ./emoji.json ./.slack-backup/emoji/
# -----------------------------------------------------------------------------
