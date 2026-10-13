@echo off
rem 從原始碼啟動 RegionPin 圖形介面（需要 uv；會跳出 UAC 要求系統管理員權限）
cd /d "%~dp0"
uv run regionpin
