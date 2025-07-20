@echo off
REM Startup script for Autonomous Agent (Windows)
REM Kills any existing processes and starts the application cleanly

setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
set "DEFAULT_PORT=5000"
set "MODE=web"
set "PORT=%DEFAULT_PORT%"
set "NO_KILL=false"
set "CHECK_ONLY=false"

REM Parse command line arguments
:parse_args
if "%~1"=="" goto end_parse
if "%~1"=="--mode" (
    set "MODE=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="-m" (
    set "MODE=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--port" (
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="-p" (
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--no-kill" (
    set "NO_KILL=true"
    shift
    goto parse_args
)
if "%~1"=="-n" (
    set "NO_KILL=true"
    shift
    goto parse_args
)
if "%~1"=="--check-only" (
    set "CHECK_ONLY=true"
    shift
    goto parse_args
)
if "%~1"=="-c" (
    set "CHECK_ONLY=true"
    shift
    goto parse_args
)
if "%~1"=="--help" goto show_usage
if "%~1"=="-h" goto show_usage
echo ❌ Unknown option: %~1
goto show_usage

:end_parse

REM Validate mode
if not "%MODE%"=="web" if not "%MODE%"=="cli" (
    echo ❌ Invalid mode: %MODE%. Must be 'web' or 'cli'
    exit /b 1
)

echo 🤖 Autonomous Agent Startup Script
echo ==================================================

REM Check dependencies
call :check_dependencies
if errorlevel 1 exit /b 1

REM Check environment
call :check_environment
if errorlevel 1 exit /b 1

if "%CHECK_ONLY%"=="true" (
    echo ✅ All checks passed!
    exit /b 0
)

REM Kill existing processes unless --no-kill is specified
if not "%NO_KILL%"=="true" (
    echo 🔄 Cleaning up existing processes...
    call :kill_port_processes %PORT%
    call :kill_python_processes
    timeout /t 2 /nobreak >nul
)

REM Start the application
if "%MODE%"=="web" (
    call :start_web
) else if "%MODE%"=="cli" (
    call :start_cli
) else (
    echo ❌ Unknown mode: %MODE%
    exit /b 1
)

exit /b 0

:check_dependencies
echo 🔍 Checking dependencies...

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed or not in PATH
    exit /b 1
)

REM Check if required Python packages are installed
python -c "import flask, langgraph, pydantic" >nul 2>&1
if errorlevel 1 (
    echo ❌ Missing required Python packages
    echo Please run: pip install -r requirements.txt
    exit /b 1
)

echo ✅ Dependencies check passed
exit /b 0

:check_environment
echo 🔍 Checking environment...

if not exist "%PROJECT_DIR%.env" (
    echo ❌ .env file not found
    echo Please create a .env file with your API keys
    exit /b 1
)

echo ✅ Environment file found
exit /b 0

:kill_port_processes
set "port=%~1"
echo 🔄 Checking for processes on port %port%...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%port%"') do (
    taskkill /F /PID %%a >nul 2>&1
    if not errorlevel 1 echo ✅ Killed process %%a on port %port%
)
exit /b 0

:kill_python_processes
echo 🔄 Checking for related Python processes...

for /f "tokens=2" %%a in ('wmic process where "name='python.exe'" get processid^,commandline /format:csv ^| findstr /i "web\\app.py\|agent.main\|agent\\main.py"') do (
    taskkill /F /PID %%a >nul 2>&1
    if not errorlevel 1 echo ✅ Killed Python process %%a
)
exit /b 0

:start_web
set "web_app=%PROJECT_DIR%web\app.py"

if not exist "%web_app%" (
    echo ❌ Web application not found at %web_app%
    exit /b 1
)

echo 🚀 Starting web application...
echo 🔗 Server will be available at: http://localhost:%DEFAULT_PORT%
echo Press Ctrl+C to stop the server
echo --------------------------------------------------

cd /d "%PROJECT_DIR%"
python "%web_app%"
exit /b 0

:start_cli
echo 🚀 Starting CLI interface...
echo Type your commands or use --help for options
echo --------------------------------------------------

cd /d "%PROJECT_DIR%"
python -m agent.main --interactive
exit /b 0

:show_usage
echo 🤖 Autonomous Agent Startup Script
echo.
echo Usage: %~nx0 [OPTIONS]
echo.
echo Options:
echo     -m, --mode MODE     Application mode: web (default) or cli
echo     -p, --port PORT     Port to check/kill processes on (default: 5000)
echo     -n, --no-kill       Skip killing existing processes
echo     -c, --check-only    Only check configuration and dependencies
echo     -h, --help          Show this help message
echo.
echo Examples:
echo     %~nx0                  # Start web interface (default)
echo     %~nx0 --mode web       # Start web interface
echo     %~nx0 --mode cli       # Start CLI interface
echo     %~nx0 --no-kill        # Don't kill existing processes
echo     %~nx0 --check-only     # Only check configuration
echo.
exit /b 0