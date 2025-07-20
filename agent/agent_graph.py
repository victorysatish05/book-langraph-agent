import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from langgraph.graph import StateGraph, END

from .state import AgentState, LLMProvider
from .planner import planner
from .tools import tool_executor
from .config import config

class AgentNodes:
    """Contains all the node functions for the LangGraph state machine."""

    @staticmethod
    async def initialize_node(state: AgentState) -> AgentState:
        """Initialize the agent session and discover tools."""
        print(f"[DEBUG_LOG] Initializing agent session...")

        # Set session metadata
        if not state.session_id:
            state.session_id = str(uuid.uuid4())
        if not state.start_time:
            state.start_time = datetime.now().isoformat()

        # Initialize tool executor and discover available tools
        try:
            await tool_executor.initialize()
            state.available_tools = tool_executor.get_available_tools()
            print(f"[DEBUG_LOG] Discovered {len(state.available_tools)} tools")
        except Exception as e:
            error_msg = f"Failed to initialize tools: {str(e)}"
            state.add_error(error_msg)
            print(f"[DEBUG_LOG] Tool initialization error: {error_msg}")

        # Add initial user message to conversation
        state.add_message("user", state.user_message)

        return state

    @staticmethod
    async def planner_node(state: AgentState) -> AgentState:
        """Plan the execution strategy using the selected LLM."""
        print(f"[DEBUG_LOG] Planning execution for goal: {state.user_goal[:100]}...")

        try:
            # Create initial plan
            plan_result = await planner.create_initial_plan(state)

            if "error" in plan_result:
                state.add_error(plan_result["error"])
                print(f"[DEBUG_LOG] Planning failed: {plan_result['error']}")
            else:
                print(f"[DEBUG_LOG] Plan created with {len(state.execution_steps)} steps")
                state.add_message("assistant", f"I've created a plan to accomplish your goal: {state.current_plan}")

        except Exception as e:
            error_msg = f"Planning node error: {str(e)}"
            state.add_error(error_msg)
            print(f"[DEBUG_LOG] {error_msg}")

        return state

    @staticmethod
    async def tool_caller_node(state: AgentState) -> AgentState:
        """Select and call the next tool in the execution plan."""
        print(f"[DEBUG_LOG] Selecting next tool to execute...")

        try:
            # Select the next tool to call
            tool_selection = await planner.select_next_tool(state)

            if not tool_selection or "error" in tool_selection:
                error_msg = tool_selection.get("error", "No tool selected") if tool_selection else "No tool selected"
                state.add_error(error_msg)
                print(f"[DEBUG_LOG] Tool selection failed: {error_msg}")
                return state

            # Check if this is a prompt_user action
            if tool_selection.get("action") == "prompt_user":
                prompt_message = tool_selection.get("prompt", "Please provide the required information.")
                print(f"[DEBUG_LOG] Prompting user: {prompt_message}")

                # Set state to indicate user input is needed
                state.needs_user_input = True
                state.add_message("assistant", prompt_message)

                # Mark this step as completed (the prompting step)
                if len(state.completed_steps) < len(state.execution_steps):
                    current_step_index = len(state.completed_steps)
                    completed_step = state.execution_steps[current_step_index]
                    state.completed_steps.append(completed_step)
                    print(f"[DEBUG_LOG] Completed prompting step: {completed_step}")

                return state

            tool_name = tool_selection.get("tool_name")
            tool_inputs = tool_selection.get("inputs", {})

            if not tool_name:
                state.add_error("No tool name provided in selection")
                return state

            print(f"[DEBUG_LOG] Calling tool: {tool_name} with inputs: {tool_inputs}")

            # Execute the selected tool
            tool_call = await tool_executor.execute_tool(tool_name, tool_inputs)

            # Store the tool call in state for final response generation
            state.tool_calls.append(tool_call)

            # Store the tool call result
            if tool_call.output:
                state.current_tool_outputs[tool_name] = tool_call.output
                print(f"[DEBUG_LOG] Tool {tool_name} executed successfully")
            elif tool_call.error:
                state.add_error(f"Tool {tool_name} failed: {tool_call.error}")
                print(f"[DEBUG_LOG] Tool {tool_name} failed: {tool_call.error}")

        except Exception as e:
            error_msg = f"Tool caller error: {str(e)}"
            state.add_error(error_msg)
            print(f"[DEBUG_LOG] {error_msg}")

        return state

    @staticmethod
    async def executor_node(state: AgentState) -> AgentState:
        """Process tool results and update execution state."""
        print(f"[DEBUG_LOG] Processing tool execution results...")

        try:
            # Mark current step as completed if we have results
            if state.current_tool_outputs and len(state.completed_steps) < len(state.execution_steps):
                current_step_index = len(state.completed_steps)
                if current_step_index < len(state.execution_steps):
                    completed_step = state.execution_steps[current_step_index]
                    state.completed_steps.append(completed_step)
                    print(f"[DEBUG_LOG] Completed step: {completed_step}")

            # Store intermediate results
            if state.current_tool_outputs:
                state.intermediate_results.append({
                    "timestamp": datetime.now().isoformat(),
                    "step": len(state.completed_steps),
                    "results": state.current_tool_outputs.copy()
                })

            # Increment iteration counter
            state.increment_iteration()
            print(f"[DEBUG_LOG] Iteration {state.iteration_count} completed")

        except Exception as e:
            error_msg = f"Executor error: {str(e)}"
            state.add_error(error_msg)
            print(f"[DEBUG_LOG] {error_msg}")

        return state

    @staticmethod
    async def evaluator_node(state: AgentState) -> AgentState:
        """Evaluate progress and decide on next actions."""
        print(f"[DEBUG_LOG] Evaluating progress...")

        try:
            # Check if we've hit the maximum iterations
            if state.iteration_count >= config.MAX_ITERATIONS:
                state.add_error(f"Maximum iterations ({config.MAX_ITERATIONS}) reached")
                state.is_complete = True
                return state

            # Check if all execution steps are completed
            if state.execution_steps and len(state.completed_steps) >= len(state.execution_steps):
                print(f"[DEBUG_LOG] All execution steps completed, marking task as complete")
                if not state.final_response:
                    final_response = await planner.generate_final_response(state)
                    state.mark_complete(final_response)
                return state

            # Check for tool validation errors and provide enhanced guidance
            if state.errors:
                # Check for validation errors in recent errors
                recent_errors = state.errors[-3:] if len(state.errors) >= 3 else state.errors
                for error in recent_errors:
                    if "invalid input for tool" in error.lower() and ("create_book" in error or "add_book" in error):
                        print(f"[DEBUG_LOG] Found validation error in state.errors: {error}")
                        # Create a mock tool call object for the enhanced guidance
                        tool_name = "create_book" if "create_book" in error else "add_book"
                        mock_tool_call = type('MockToolCall', (), {
                            'name': tool_name,
                            'error': error
                        })()
                        enhanced_guidance = await AgentNodes._provide_enhanced_error_guidance(state, mock_tool_call)
                        if enhanced_guidance:
                            state.mark_complete(enhanced_guidance)
                            return state
                        break

                # Also check tool_calls for errors (original logic)
                if state.tool_calls:
                    last_tool_call = state.tool_calls[-1] if state.tool_calls else None
                    if last_tool_call and last_tool_call.error:
                        enhanced_guidance = await AgentNodes._provide_enhanced_error_guidance(state, last_tool_call)
                        if enhanced_guidance:
                            state.mark_complete(enhanced_guidance)
                            return state

            # Evaluate current progress
            evaluation = await planner.evaluate_progress(state)

            next_action = evaluation.get("next_action", "continue")
            print(f"[DEBUG_LOG] Evaluation result: {next_action}")

            # Add evaluation message to conversation
            if evaluation.get("evaluation"):
                state.add_message("assistant", f"Progress update: {evaluation['evaluation']}")

            # Handle different evaluation outcomes
            if next_action == "complete":
                print(f"[DEBUG_LOG] Task marked as complete by evaluation")
            elif next_action == "user_input":
                print(f"[DEBUG_LOG] Waiting for user input")
            elif next_action == "error":
                print(f"[DEBUG_LOG] Evaluation indicated error")
            elif next_action == "continue":
                # If we're continuing but have no more steps and no tools called, complete the task
                if (not state.execution_steps or 
                    len(state.completed_steps) >= len(state.execution_steps)) and not state.tool_calls:
                    print(f"[DEBUG_LOG] No more steps to execute and no tools called, completing task")
                    if not state.final_response:
                        final_response = await planner.generate_final_response(state)
                        state.mark_complete(final_response)

        except Exception as e:
            error_msg = f"Evaluator error: {str(e)}"
            state.add_error(error_msg)
            print(f"[DEBUG_LOG] {error_msg}")
            # Mark as complete on evaluator error to prevent infinite loops
            if not state.is_complete:
                state.mark_complete(f"Task completed with evaluation error: {error_msg}")

        return state

    @staticmethod
    async def _provide_enhanced_error_guidance(state: AgentState, failed_tool_call) -> str:
        """Provide enhanced guidance when tool validation fails."""
        try:
            # Check if this is a book creation validation error (create_book or add_book)
            if failed_tool_call.name in ["create_book", "add_book"] and "invalid" in failed_tool_call.error.lower():
                print(f"[DEBUG_LOG] Providing enhanced guidance for {failed_tool_call.name} validation error")

                # Get available tools to understand the schema
                available_tools = tool_executor.get_available_tools()
                book_tool = None
                for tool in available_tools:
                    if tool.name == failed_tool_call.name:
                        book_tool = tool
                        break

                if book_tool:
                    # Extract schema information
                    schema = book_tool.input_schema
                    properties = schema.get("properties", {})
                    required_fields = schema.get("required", [])

                    guidance_parts = [
                        "I was unable to add a book to your library due to input validation issues.",
                        "",
                        "To successfully add a book, please provide the following information:"
                    ]

                    # Add detailed field requirements
                    for field_name, field_info in properties.items():
                        field_type = field_info.get("type", "string")
                        field_desc = field_info.get("description", "")
                        required_marker = " (required)" if field_name in required_fields else " (optional)"

                        if field_name in ["year", "publishedYear"]:
                            guidance_parts.append(f"• **{field_name.replace('published', 'Published ').title()}**: Must be an integer representing the publication year (e.g., 1997, 2024){required_marker}")
                        elif field_name == "title":
                            guidance_parts.append(f"• **{field_name.title()}**: Text string with the book's title{required_marker}")
                        elif field_name == "author":
                            guidance_parts.append(f"• **{field_name.title()}**: Text string with the author's name{required_marker}")
                        elif field_name == "genre":
                            guidance_parts.append(f"• **{field_name.title()}**: Text string describing the book's genre{required_marker}")
                        elif field_name == "isbn":
                            guidance_parts.append(f"• **{field_name.title()}**: Text string with the ISBN number{required_marker}")
                        else:
                            guidance_parts.append(f"• **{field_name.title()}**: {field_type} - {field_desc}{required_marker}")

                    guidance_parts.extend([
                        "",
                        "**Example format:**",
                        "Title: The Great Gatsby",
                        "Author: F. Scott Fitzgerald", 
                        "Genre: Classic Literature",
                        "Year: 1925",
                        "ISBN: 978-0-7432-7356-5",
                        "",
                        "Please try again with the correct format, ensuring the publication year is entered as a number without quotes."
                    ])

                    return "\n".join(guidance_parts)

            # For other validation errors, provide general guidance
            elif "invalid" in failed_tool_call.error.lower():
                return f"I encountered a validation error with the {failed_tool_call.name} tool: {failed_tool_call.error}\n\nPlease check that all required fields are provided in the correct format and try again."

        except Exception as e:
            print(f"[DEBUG_LOG] Error providing enhanced guidance: {str(e)}")

        return None

    @staticmethod
    async def finish_node(state: AgentState) -> AgentState:
        """Generate final response and complete the session."""
        print(f"[DEBUG_LOG] Generating final response...")

        try:
            # If we need user input, don't generate a new final response
            # The specific prompt has already been added to the conversation
            if state.needs_user_input:
                # Use the last assistant message as the final response
                if state.messages and state.messages[-1].role == "assistant":
                    state.mark_complete(state.messages[-1].content)
                else:
                    state.mark_complete("Please provide more information to continue.")
                print(f"[DEBUG_LOG] Session completed with user input request")
            else:
                # Generate final response if not already set
                if not state.final_response:
                    final_response = await planner.generate_final_response(state)
                    state.mark_complete(final_response)

                # Add final response to conversation
                state.add_message("assistant", state.final_response)
                print(f"[DEBUG_LOG] Session completed successfully")

        except Exception as e:
            error_msg = f"Finish node error: {str(e)}"
            state.add_error(error_msg)
            state.mark_complete(f"Task completed with errors: {error_msg}")
            print(f"[DEBUG_LOG] {error_msg}")

        return state

def should_continue(state: AgentState) -> str:
    """Determine the next node based on current state."""

    # If task is complete, go to finish
    if state.is_complete:
        return "finish"

    # If there are critical errors, go to finish
    if state.errors and len(state.errors) > 3:  # Too many errors
        state.is_complete = True
        return "finish"

    # If waiting for user input, pause (this would be handled by the web interface)
    if state.needs_user_input:
        return "finish"  # For now, finish when user input is needed

    # If we have no execution steps, we need to plan
    if not state.execution_steps:
        return "planner"

    # If all steps are completed, evaluate
    if len(state.completed_steps) >= len(state.execution_steps):
        return "finish"

    # If we have steps to execute, call tools
    return "tool_caller"

def create_agent_graph():
    """Create and configure the LangGraph state machine."""

    # Create the state graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("initialize", AgentNodes.initialize_node)
    workflow.add_node("planner", AgentNodes.planner_node)
    workflow.add_node("tool_caller", AgentNodes.tool_caller_node)
    workflow.add_node("executor", AgentNodes.executor_node)
    workflow.add_node("evaluator", AgentNodes.evaluator_node)
    workflow.add_node("finish", AgentNodes.finish_node)

    # Set entry point
    workflow.set_entry_point("initialize")

    # Add edges
    workflow.add_edge("initialize", "planner")
    workflow.add_edge("planner", "tool_caller")
    workflow.add_edge("tool_caller", "executor")
    workflow.add_edge("executor", "evaluator")

    # Add conditional edges from evaluator
    workflow.add_conditional_edges(
        "evaluator",
        should_continue,
        {
            "planner": "planner",
            "tool_caller": "tool_caller",
            "finish": "finish"
        }
    )

    # Finish node ends the workflow
    workflow.add_edge("finish", END)

    # Compile the graph
    return workflow.compile()

class AutonomousAgent:
    """High-level interface for the autonomous agent."""

    def __init__(self):
        self.graph = create_agent_graph()

    async def run(
        self, 
        user_goal: str, 
        user_message: str = None,
        selected_llm: LLMProvider = None
    ) -> AgentState:
        """Run the autonomous agent with the given goal."""

        # Create initial state
        initial_state = AgentState(
            user_goal=user_goal,
            user_message=user_message or user_goal,
            selected_llm=selected_llm or LLMProvider.GEMINI
        )

        print(f"[DEBUG_LOG] Starting agent execution for goal: {user_goal}")

        try:
            # Execute the graph
            result = await self.graph.ainvoke(initial_state)

            # LangGraph returns a dictionary-like object, extract the actual state
            if isinstance(result, dict):
                # LangGraph returns the final state directly in the result
                # The result should be the AgentState itself or contain it
                final_state = result
                if not isinstance(final_state, AgentState):
                    print(f"[DEBUG_LOG] Result type: {type(result)}, extracting AgentState")
                    # For LangGraph AddableValuesDict, the state is the result itself
                    # We need to convert it back to AgentState while preserving all data
                    final_state = AgentState(
                        user_goal=result.get('user_goal', initial_state.user_goal),
                        user_message=result.get('user_message', initial_state.user_message),
                        selected_llm=result.get('selected_llm', initial_state.selected_llm)
                    )

                    # Copy all the important state data
                    final_state.session_id = result.get('session_id', initial_state.session_id)
                    final_state.current_plan = result.get('current_plan', '')
                    final_state.execution_steps = result.get('execution_steps', [])
                    final_state.completed_steps = result.get('completed_steps', [])
                    final_state.tool_calls = result.get('tool_calls', [])
                    final_state.current_tool_outputs = result.get('current_tool_outputs', {})
                    final_state.intermediate_results = result.get('intermediate_results', [])
                    final_state.messages = result.get('messages', [])
                    final_state.errors = result.get('errors', [])
                    final_state.iteration_count = result.get('iteration_count', 0)
                    final_state.is_complete = result.get('is_complete', False)
                    final_state.final_response = result.get('final_response', '')
                    final_state.needs_user_input = result.get('needs_user_input', False)
                    final_state.available_tools = result.get('available_tools', [])
            else:
                final_state = result

            print(f"[DEBUG_LOG] Agent execution completed, final_state type: {type(final_state)}")
            return final_state

        except Exception as e:
            print(f"[DEBUG_LOG] Agent execution failed: {str(e)}")
            initial_state.add_error(f"Agent execution failed: {str(e)}")
            initial_state.mark_complete(f"Sorry, I encountered an error: {str(e)}")
            return initial_state

    async def run_streaming(
        self,
        user_goal: str,
        user_message: str = None,
        selected_llm: LLMProvider = None
    ):
        """Run the agent with streaming updates."""

        # Create initial state
        initial_state = AgentState(
            user_goal=user_goal,
            user_message=user_message or user_goal,
            selected_llm=selected_llm or LLMProvider.GEMINI
        )

        print(f"[DEBUG_LOG] Starting streaming agent execution")

        try:
            # Stream the execution
            async for state in self.graph.astream(initial_state):
                yield state

        except Exception as e:
            print(f"[DEBUG_LOG] Streaming execution failed: {str(e)}")
            error_state = initial_state
            error_state.add_error(f"Streaming execution failed: {str(e)}")
            yield error_state

# Global agent instance
agent = AutonomousAgent()
