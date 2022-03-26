#!/usr/bin/bash

mkdir -p log
if [ $# -lt 1 ] ; then
    tput setaf 1
    echo "Running this script without arguments will lead to backing up ALL available channels/conversations."
    echo "That's probably not what you want as it will take A LOT of time (unless you know what you are doing)"
    echo "You can back up neccessary channels only (comma-separated): '$0 <channel1>,<channel2>'"
    tput sgr0
    read -r -p "Continue (y/n)? " yn
    case $yn in
      [Yy]*) ;;
          *) echo "Terminating" ; exit 1 ;;
    esac
    venv/bin/python -m pyslacker -cr
    exit 0
fi

venv/bin/python -m pyslacker -cr --ch "$@"
