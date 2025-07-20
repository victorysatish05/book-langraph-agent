#!/bin/bash

# Startup script for Autonomous Agent (Unix/Linux/macOS)
# Kills any existing processes and starts the application cleanly

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PORT=5000

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

print_info() {
    echo -e "${BLUE}🔗${NC} $1"
}

# Function to kill processes on a specific port
kill_port_processes() {
    local port=$1
    echo "🔄 Checking for processes on port $port..."
    
    if command -v lsof >/dev/null 2>&1; then
        local pids=$(lsof -ti :$port 2>/dev/null || true)
        if [ ! -z "$pids" ]; then
            echo "$pids" | while read pid; do
                if [ ! -z "$pid" ]; then
                    kill -TERM "$pid" 2>/dev/null || true
                    print_status "Killed process $pid on port $port"
                    sleep 1
                    # Force kill if still running
                    kill -KILL "$pid" 2>/dev/null || true
                fi
            done
        else
            echo "No processes found on port $port"
        fi
    else
        print_warning "lsof not available, skipping port cleanup"
    fi
}

# Function to kill Python processes related to this application
kill_python_processes() {
    echo "🔄 Checking for related Python processes..."
    
    local project_name=$(basename "$PROJECT_DIR")
    local killed=false
    
    # Find and kill processes containing our project keywords
    ps aux | grep python | grep -E "(web/app\.py|agent\.main|agent/main\.py|$project_name)" | grep -v grep | while read line; do
        local pid=$(echo "$line" | awk '{print $2}')
        if [ ! -z "$pid" ]; then
            kill -TERM "$pid" 2>/dev/null || true
            print_status "Killed Python process $pid"
            killed=true
            sleep 1
            # Force kill if still running
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done
    
    if [ "$killed" = false ]; then
        echo "No related Python processes found"
    fi
}

# Function to check dependencies
check_dependencies() {
    echo "🔍 Checking dependencies..."
    
    # Check if Python is available
    if ! command -v python3 >/dev/null 2>&1; then
        print_error "Python 3 is not installed"
        return 1
    fi
    
    # Check if required Python packages are installed
    if ! python3 -c "import flask, langgraph, pydantic" 2>/dev/null; then
        print_error "Missing required Python packages"
        echo "Please run: pip install -r requirements.txt"
        return 1
    fi
    
    print_status "Dependencies check passed"
    return 0
}

# Function to check environment
check_environment() {
    echo "🔍 Checking environment..."
    
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        print_error ".env file not found"
        echo "Please create a .env file with your API keys"
        return 1
    fi
    
    print_status "Environment file found"
    return 0
}

# Function to start web application
start_web() {
    local web_app="$PROJECT_DIR/web/app.py"
    
    if [ ! -f "$web_app" ]; then
        print_error "Web application not found at $web_app"
        return 1
    fi
    
    echo "🚀 Starting web application..."
    print_info "Server will be available at: http://localhost:$DEFAULT_PORT"
    echo "Press Ctrl+C to stop the server"
    echo "$(printf '%.0s-' {1..50})"
    
    cd "$PROJECT_DIR"
    python3 "$web_app"
}

# Function to start CLI
start_cli() {
    echo "🚀 Starting CLI interface..."
    echo "Type your commands or use --help for options"
    echo "$(printf '%.0s-' {1..50})"
    
    cd "$PROJECT_DIR"
    python3 -m agent.main --interactive
}

# Function to show usage
show_usage() {
    cat << EOF
🤖 Autonomous Agent Startup Script

Usage: $0 [OPTIONS]

Options:
    -m, --mode MODE     Application mode: web (default) or cli
    -p, --port PORT     Port to check/kill processes on (default: 5000)
    -n, --no-kill       Skip killing existing processes
    -c, --check-only    Only check configuration and dependencies
    -h, --help          Show this help message

Examples:
    $0                  # Start web interface (default)
    $0 --mode web       # Start web interface
    $0 --mode cli       # Start CLI interface
    $0 --no-kill        # Don't kill existing processes
    $0 --check-only     # Only check configuration

EOF
}

# Parse command line arguments
MODE="web"
PORT=$DEFAULT_PORT
NO_KILL=false
CHECK_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -n|--no-kill)
            NO_KILL=true
            shift
            ;;
        -c|--check-only)
            CHECK_ONLY=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Validate mode
if [[ "$MODE" != "web" && "$MODE" != "cli" ]]; then
    print_error "Invalid mode: $MODE. Must be 'web' or 'cli'"
    exit 1
fi

# Main execution
echo "🤖 Autonomous Agent Startup Script"
echo "$(printf '%.0s=' {1..50})"

# Check dependencies and environment
if ! check_dependencies; then
    exit 1
fi

if ! check_environment; then
    exit 1
fi

if [ "$CHECK_ONLY" = true ]; then
    print_status "All checks passed!"
    exit 0
fi

# Kill existing processes unless --no-kill is specified
if [ "$NO_KILL" = false ]; then
    echo "🔄 Cleaning up existing processes..."
    kill_port_processes "$PORT"
    kill_python_processes
    sleep 2  # Give processes time to clean up
fi

# Start the application
case $MODE in
    web)
        start_web
        ;;
    cli)
        start_cli
        ;;
    *)
        print_error "Unknown mode: $MODE"
        exit 1
        ;;
esac