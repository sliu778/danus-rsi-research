@echo off
pushd "%~dp0.."
python -m danus_rsi %*
set "run_result=%ERRORLEVEL%"
popd
exit /b %run_result%
