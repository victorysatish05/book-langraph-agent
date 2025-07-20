#!/usr/bin/env python3
"""
Startup script for the Autonomous Agent application.
Kills any existing processes and starts the application cleanly.
"""

import os
import sys
import signal
import subprocess
import time
import argparse
import platform
from pathlib import Path

def get_project_root():
    """Get the project root directory."""
    return Path(__file__).parent.absolute()

def kill_processes_by_port(port):
    """Kill processes running on a specific port."""
    system = platform.system().lower()

    try:
        if system in ['linux', 'darwin']:  # Linux or macOS
            # Find processes using the port
            result = subprocess.run(['lsof', '-ti', f':{port}'], 
                                  capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        print(f"✅ Killed process {pid} on port {port}")
                        time.sleep(1)
                        # Force kill if still running
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    except (ValueError, ProcessLookupError):
                        continue
        elif system == 'windows':
            # Windows approach
            result = subprocess.run(['netstat', '-ano'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if f':{port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) > 4:
                            pid = parts[-1]
                            try:
                                subprocess.run(['taskkill', '/F', '/PID', pid], 
                                             capture_output=True)
                                print(f"✅ Killed process {pid} on port {port}")
                            except:
                                continue
    except FileNotFoundError:
        print(f"⚠️  Could not find tools to kill processes on port {port}")
    except Exception as e:
        print(f"⚠️  Error killing processes on port {port}: {e}")

def kill_python_processes():
    """Kill Python processes related to this application."""
    system = platform.system().lower()
    project_root = str(get_project_root())

    try:
        if system in ['linux', 'darwin']:  # Linux or macOS
            # Find Python processes containing our project path
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'python' in line and any(keyword in line for keyword in [
                        'web/app.py', 'agent.main', 'agent/main.py', project_root
                    ]):
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[1])
                                os.kill(pid, signal.SIGTERM)
                                print(f"✅ Killed Python process {pid}")
                                time.sleep(1)
                                # Force kill if still running
                                try:
                                    os.kill(pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                            except (ValueError, ProcessLookupError):
                                continue
        elif system == 'windows':
            # Windows approach
            result = subprocess.run(['wmic', 'process', 'where', 
                                   'name="python.exe"', 'get', 'processid,commandline'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if any(keyword in line for keyword in [
                        'web\\app.py', 'agent.main', 'agent\\main.py'
                    ]):
                        # Extract PID from the line
                        parts = line.strip().split()
                        if parts:
                            try:
                                pid = parts[-1]
                                subprocess.run(['taskkill', '/F', '/PID', pid], 
                                             capture_output=True)
                                print(f"✅ Killed Python process {pid}")
                            except:
                                continue
    except Exception as e:
        print(f"⚠️  Error killing Python processes: {e}")

def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import flask
        import langgraph
        import pydantic
        print("✅ Core dependencies found")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def check_environment():
    """Check environment configuration."""
    env_file = get_project_root() / '.env'
    if not env_file.exists():
        print("❌ .env file not found")
        print("Please create a .env file with your API keys")
        return False

    print("✅ Environment file found")
    return True


def start_web_app():
    """Start the web application."""
    project_root = get_project_root()
    web_app_path = project_root / 'web' / 'app.py'

    if not web_app_path.exists():
        print("❌ Web application not found")
        return False

    print("🚀 Starting web application...")
    print("🔗 Web app will be available at: http://localhost:5001")
    print("Press Ctrl+C to stop the server")
    print("-" * 50)

    try:
        # Change to project directory
        os.chdir(project_root)

        # Start the web application
        subprocess.run([sys.executable, str(web_app_path)])
        return True
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
        return True
    except Exception as e:
        print(f"❌ Failed to start web application: {e}")
        return False

def start_cli():
    """Start the CLI interface."""
    project_root = get_project_root()

    print("🚀 Starting CLI interface...")
    print("Type your commands or use --help for options")
    print("-" * 50)

    try:
        # Change to project directory
        os.chdir(project_root)

        # Start the CLI
        subprocess.run([sys.executable, '-m', 'agent.main', '--interactive'])
        return True
    except KeyboardInterrupt:
        print("\n🛑 CLI stopped by user")
        return True
    except Exception as e:
        print(f"❌ Failed to start CLI: {e}")
        return False

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Startup script for Autonomous Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start.py                    # Start web interface (default)
  python start.py --mode web         # Start web interface
  python start.py --mode cli         # Start CLI interface
  python start.py --no-kill          # Don't kill existing processes
  python start.py --check-only       # Only check configuration
        """
    )

    parser.add_argument(
        '--mode', '-m',
        choices=['web', 'cli'],
        default='web',
        help='Application mode to start (default: web)'
    )

    parser.add_argument(
        '--no-kill',
        action='store_true',
        help='Skip killing existing processes'
    )

    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Only check configuration and dependencies'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Port to check/kill processes on (default: 5000)'
    )

    args = parser.parse_args()

    print("🤖 Autonomous Agent Startup Script")
    print("=" * 50)

    # Check dependencies and environment
    if not check_dependencies():
        sys.exit(1)

    if not check_environment():
        sys.exit(1)

    if args.check_only:
        print("✅ All checks passed!")
        return

    # Kill existing processes unless --no-kill is specified
    if not args.no_kill:
        print("🔄 Cleaning up existing processes...")
        kill_processes_by_port(args.port)  # Flask app port
        kill_python_processes()
        time.sleep(2)  # Give processes time to clean up

    # Start the application
    if args.mode == 'web':
        success = start_web_app()
    elif args.mode == 'cli':
        success = start_cli()
    else:
        print(f"❌ Unknown mode: {args.mode}")
        sys.exit(1)

    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()
