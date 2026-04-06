#!/bin/bash
# 開発用ホットリロード起動スクリプト
echo "Starting bot with hot reloading (watchdog)..."
echo "Editing Python files in ./src will automatically restart the bot."
watchmedo auto-restart --directory=./src --pattern="*.py" --recursive -- python -m src.main
