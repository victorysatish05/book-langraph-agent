#!/usr/bin/env python3
"""
Main entry point for the autonomous agent.
Provides both CLI and programmatic interfaces.
"""

import asyncio
import sys
from typing import Optional
import argparse

from .agent_graph import agent
from .state import LLMProvider
from .config import config
from .llm_router import llm_router

async def run_agent_cli(
    goal: str,
    message: Optional[str] = None,
    llm_provider: Optional[str] = None,
    streaming: bool = False
):
    """Run the agent from command line interface."""

    print("🤖 Autonomous Agent Starting...")
    print(f"Goal: {goal}")

    # Validate and set LLM provider
    selected_llm = LLMProvider.GEMINI  # default
    if llm_provider:
        try:
            selected_llm = LLMProvider(llm_provider.lower())
        except ValueError:
            print(f"❌ Invalid LLM provider: {llm_provider}")
            print(f"Available providers: {', '.join([p.value for p in LLMProvider])}")
            return

    # Check if the selected provider is available
    available_providers = llm_router.get_available_providers()
    if selected_llm not in available_providers:
        print(f"❌ LLM provider '{selected_llm.value}' is not properly configured")
        print(f"Available providers: {', '.join([p.value for p in available_providers])}")
        if available_providers:
            selected_llm = available_providers[0]
            print(f"🔄 Falling back to: {selected_llm.value}")
        else:
            print("❌ No LLM providers are configured. Please check your .env file.")
            return

    print(f"🧠 Using LLM: {selected_llm.value}")
    print("-" * 50)

    try:
        if streaming:
            # Run with streaming updates
            print("📡 Streaming mode enabled...")
            async for state_update in agent.run_streaming(
                user_goal=goal,
                user_message=message,
                selected_llm=selected_llm
            ):
                # Print streaming updates
                if hasattr(state_update, 'current_plan') and state_update.current_plan:
                    print(f"📋 Plan: {state_update.current_plan}")

                if hasattr(state_update, 'current_tool_outputs') and state_update.current_tool_outputs:
                    for tool_name, output in state_update.current_tool_outputs.items():
                        print(f"🔧 Tool {tool_name}: {str(output)[:100]}...")

                if hasattr(state_update, 'is_complete') and state_update.is_complete:
                    print("\n✅ Task completed!")
                    if hasattr(state_update, 'final_response'):
                        print(f"📝 Final Response: {state_update.final_response}")
                    break
        else:
            # Run normally
            final_state = await agent.run(
                user_goal=goal,
                user_message=message,
                selected_llm=selected_llm
            )

            # Display results
            print("\n" + "="*50)
            print("📊 EXECUTION SUMMARY")
            print("="*50)

            print(f"✅ Completed: {final_state.is_complete}")
            print(f"🔄 Iterations: {final_state.iteration_count}")
            print(f"🔧 Tools used: {len(final_state.tool_calls)}")
            print(f"❌ Errors: {len(final_state.errors)}")

            if final_state.execution_steps:
                print(f"\n📋 Execution Steps ({len(final_state.completed_steps)}/{len(final_state.execution_steps)} completed):")
                for i, step in enumerate(final_state.execution_steps):
                    status = "✅" if i < len(final_state.completed_steps) else "⏳"
                    print(f"  {status} {step}")

            if final_state.tool_calls:
                print(f"\n🔧 Tool Calls:")
                for tool_call in final_state.tool_calls:
                    status = "✅" if tool_call.output else "❌" if tool_call.error else "⏳"
                    print(f"  {status} {tool_call.name}")
                    if tool_call.error:
                        print(f"    Error: {tool_call.error}")

            if final_state.errors:
                print(f"\n❌ Errors:")
                for error in final_state.errors:
                    print(f"  • {error}")

            print(f"\n📝 Final Response:")
            print("-" * 30)
            print(final_state.final_response or "No final response generated.")

    except KeyboardInterrupt:
        print("\n🛑 Execution interrupted by user")
    except Exception as e:
        print(f"\n❌ Execution failed: {str(e)}")
        import traceback
        traceback.print_exc()

def check_configuration():
    """Check if the agent is properly configured."""
    print("🔍 Checking configuration...")

    # Check API keys
    api_key_status = config.validate_api_keys()
    print("\n🔑 API Key Status:")
    for provider, is_valid in api_key_status.items():
        status = "✅" if is_valid else "❌"
        print(f"  {status} {provider.upper()}: {'Configured' if is_valid else 'Not configured'}")

    # Check available providers
    try:
        available_providers = llm_router.get_available_providers()
        print(f"\n🧠 Available LLM Providers: {', '.join([p.value for p in available_providers])}")

        if not available_providers:
            print("⚠️  No LLM providers are available. Please configure at least one API key.")
            return False
    except Exception as e:
        print(f"❌ Error checking LLM providers: {e}")
        return False

    # Check MCP server configuration
    print(f"\n🔗 MCP Server: {config.MCP_SERVER_BASE_URL}")
    print(f"🔗 Tools Endpoint: {config.MCP_TOOLS_URL}")

    print("\n✅ Configuration check completed!")
    return True

async def interactive_mode():
    """Run the agent in interactive mode."""
    print("🤖 Autonomous Agent - Interactive Mode")
    print("Type 'quit' or 'exit' to stop, 'help' for commands")
    print("-" * 50)

    # Check configuration first
    if not check_configuration():
        print("❌ Configuration issues detected. Please fix them before continuing.")
        return

    # Get available providers
    available_providers = llm_router.get_available_providers()
    current_llm = available_providers[0] if available_providers else LLMProvider.GEMINI

    while True:
        try:
            print(f"\n🧠 Current LLM: {current_llm.value}")
            user_input = input("👤 Enter your goal: ").strip()

            if user_input.lower() in ['quit', 'exit', 'q']:
                print("👋 Goodbye!")
                break
            elif user_input.lower() == 'help':
                print("""
Available commands:
  help          - Show this help message
  config        - Check configuration
  llm <provider> - Switch LLM provider (gemini, openai, anthropic)
  quit/exit     - Exit interactive mode

Just type your goal to run the agent!
""")
                continue
            elif user_input.lower() == 'config':
                check_configuration()
                continue
            elif user_input.lower().startswith('llm '):
                provider_name = user_input[4:].strip().lower()
                try:
                    new_llm = LLMProvider(provider_name)
                    if new_llm in available_providers:
                        current_llm = new_llm
                        print(f"✅ Switched to {current_llm.value}")
                    else:
                        print(f"❌ Provider {provider_name} is not available")
                        print(f"Available: {', '.join([p.value for p in available_providers])}")
                except ValueError:
                    print(f"❌ Invalid provider: {provider_name}")
                    print(f"Valid providers: {', '.join([p.value for p in LLMProvider])}")
                continue
            elif not user_input:
                continue

            # Run the agent
            print(f"\n🚀 Executing: {user_input}")
            print("-" * 30)

            await run_agent_cli(
                goal=user_input,
                llm_provider=current_llm.value,
                streaming=False
            )

        except KeyboardInterrupt:
            print("\n🛑 Interrupted. Type 'quit' to exit.")
        except EOFError:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Autonomous Agent with LangGraph and Multi-LLM Support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m agent.main "Summarize the latest news about AI"
  python -m agent.main "Find information about Python" --llm openai
  python -m agent.main "Help me plan a trip" --streaming
  python -m agent.main --interactive
  python -m agent.main --config
        """
    )

    parser.add_argument(
        "goal",
        nargs="?",
        help="The goal or task for the agent to accomplish"
    )

    parser.add_argument(
        "--message", "-m",
        help="Additional message or context for the goal"
    )

    parser.add_argument(
        "--llm",
        choices=["gemini", "openai", "anthropic"],
        help="LLM provider to use (default: gemini)"
    )

    parser.add_argument(
        "--streaming", "-s",
        action="store_true",
        help="Enable streaming mode for real-time updates"
    )

    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode"
    )

    parser.add_argument(
        "--config", "-c",
        action="store_true",
        help="Check configuration and exit"
    )

    args = parser.parse_args()

    # Handle configuration check
    if args.config:
        check_configuration()
        return

    # Handle interactive mode
    if args.interactive:
        asyncio.run(interactive_mode())
        return

    # Require goal for non-interactive mode
    if not args.goal:
        parser.error("Goal is required unless using --interactive or --config")

    # Run the agent
    asyncio.run(run_agent_cli(
        goal=args.goal,
        message=args.message,
        llm_provider=args.llm,
        streaming=args.streaming
    ))

if __name__ == "__main__":
    main()
