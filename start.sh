#!/bin/bash
cd "$(dirname "$0")"
while true; do
    # Truncate log if > 10MB
    [ $(stat -c%s crash.log 2>/dev/null || echo 0) -gt 10000000 ] && tail -n 2000 crash.log > crash.log.tmp && mv crash.log.tmp crash.log
    echo "Starting server..." >> crash.log
    ./venv/bin/python server.py >> crash.log 2>&1
    echo "Server crashed with exit code $?. Restarting in 5 seconds..." >> crash.log
    sleep 5
done
