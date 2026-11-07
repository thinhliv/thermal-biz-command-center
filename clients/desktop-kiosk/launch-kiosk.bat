@echo off
setlocal
title Thermal ^& Business Command Center - TV Kiosk

REM ============================================================
REM   MAN HINH TV KIOSK CHO BAN GIAM DOC
REM
REM   Uu tien ban desktop (Electron) vi no tu noi backend va
REM   chay --kiosk that su (an thanh tieu de, khoa phim tat).
REM   Khong tim thay thi moi dung trinh duyet o che do kiosk.
REM
REM   Hai bien tuy chinh (khong bat buoc):
REM     THERMAL_KIOSK_URL  dia chi ban web, mac dinh http://localhost:5173
REM     THERMAL_KIOSK_EXE  duong dan ThermalBiz.exe neu cai o cho khac
REM ============================================================

if not defined THERMAL_KIOSK_URL set "THERMAL_KIOSK_URL=http://localhost:5173"

REM electron-builder (NSIS, perMachine=false) cai vao %LOCALAPPDATA%\Programs\<productName>.
set "EXE_USER=%LOCALAPPDATA%\Programs\Thermal & Biz Command Center\ThermalBiz.exe"
set "EXE_MACHINE=%ProgramFiles%\Thermal & Biz Command Center\ThermalBiz.exe"

set "EXE="
if defined THERMAL_KIOSK_EXE set "EXE=%THERMAL_KIOSK_EXE%"
if not defined EXE if exist "%EXE_USER%" set "EXE=%EXE_USER%"
if not defined EXE if exist "%EXE_MACHINE%" set "EXE=%EXE_MACHINE%"

if defined EXE goto :run_desktop

echo Khong tim thay ban desktop da cai.
echo Mo trinh duyet o che do kiosk toi: %THERMAL_KIOSK_URL%
echo.
start msedge --kiosk "%THERMAL_KIOSK_URL%" --edge-kiosk-type=fullscreen || start chrome --kiosk "%THERMAL_KIOSK_URL%"
goto :done

:run_desktop
echo Dang mo ban desktop o che do kiosk toan man hinh...
echo   %EXE%
echo.
start "" "%EXE%" --kiosk

:done
REM Kiosk khong co nguoi ngoi canh: dong cua so cmd nay de TV chi con dung man hinh dieu hanh.
exit /b 0
