import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from .state import AgentState, LLMProvider, ToolMetadata
from .llm_router import llm_router
from .tools import tool_executor

class AgentPlanner:
    """Handles planning and decision-making for the autonomous agent."""

    def __init__(self):
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the planning LLM."""
        return """You are an autonomous agent planner. Your role is to analyze user goals and create execution plans using available tools.

CAPABILITIES:
- Analyze user requests and break them down into actionable steps
- Select appropriate tools from the available toolkit
- Create detailed execution plans with proper sequencing
- Evaluate results and decide on next actions
- Provide clear, helpful responses to users

IMPORTANT CONSTRAINTS:
- ONLY use tools that are explicitly listed in the AVAILABLE TOOLS section
- DO NOT assume the existence of calculation tools like "python", "length", "count", "math", etc.
- For data processing tasks (counting, calculations, analysis), plan to retrieve the data first, then process it in the final response
- If you need to count items or perform calculations on retrieved data, do this during the final response generation, not as a separate tool call

GUIDELINES:
1. Always start by understanding the user's goal clearly
2. Review available tools and their capabilities carefully - only use tools that are actually available
3. Create a step-by-step plan that logically progresses toward the goal
4. For counting/calculation tasks: retrieve data with available tools, then process the results directly
5. Consider dependencies between steps
6. Be specific about tool inputs and expected outputs
7. Handle errors gracefully and suggest alternatives
8. Provide clear status updates and final results

HANDLING MISSING PARAMETERS:
- If a tool requires parameters that the user hasn't provided, create a plan that includes prompting the user for those parameters
- Use action type "prompt_user" to request missing information
- After getting user input, proceed with the tool call
- Be specific about what information is needed and why

RESPONSE FORMAT:
When creating a plan, respond with a JSON object containing:
{
    "analysis": "Brief analysis of the user's request",
    "plan": [
        {
            "step": 1,
            "action": "prompt_user" | "tool_call",
            "tool_name": "tool_name" (only for tool_call actions),
            "description": "What this step accomplishes",
            "inputs": {"key": "value"} (only for tool_call actions),
            "prompt": "Question to ask user" (only for prompt_user actions),
            "expected_output": "What we expect to get"
        }
    ],
    "reasoning": "Why this approach was chosen"
}</SEARCH>

When evaluating results, respond with:
{
    "evaluation": "Assessment of current progress",
    "next_action": "continue|complete|error|user_input",
    "reasoning": "Why this decision was made",
    "response": "Message to user (if completing or need input)"
}
"""

    async def create_initial_plan(self, state: AgentState) -> Dict[str, Any]:
        """Create an initial execution plan based on the user's goal."""
        # Prepare context for the LLM
        available_tools_desc = tool_executor.get_tools_description()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""
USER GOAL: {state.user_goal}
USER MESSAGE: {state.user_message}

AVAILABLE TOOLS:
{available_tools_desc}

CONVERSATION CONTEXT:
{state.get_conversation_context()}

Please create a detailed execution plan to accomplish the user's goal.
"""}
        ]

        try:
            response, used_provider = await llm_router.generate_with_fallback(
                messages=messages,
                preferred_provider=state.selected_llm
            )

            # Update state with the provider that was actually used
            state.selected_llm = used_provider

            # Parse the response
            plan_data = self._parse_plan_response(response)

            # Update state with the plan
            state.current_plan = plan_data.get("analysis", "")
            state.execution_steps = []

            # Store the original plan data for later reference
            state.original_plan_steps = plan_data.get("plan", [])

            for step in plan_data.get("plan", []):
                if step.get("action") == "prompt_user":
                    state.execution_steps.append(f"Step {step['step']}: {step['description']} (Prompt: {step.get('prompt', 'Ask user for input')})")
                else:
                    state.execution_steps.append(f"Step {step['step']}: {step['description']}")

            return plan_data

        except Exception as e:
            error_msg = f"Failed to create plan: {str(e)}"
            state.add_error(error_msg)
            return {
                "error": error_msg,
                "analysis": "Unable to create execution plan",
                "plan": [],
                "reasoning": "LLM planning failed"
            }

    async def evaluate_progress(self, state: AgentState) -> Dict[str, Any]:
        """Evaluate current progress and decide on next actions."""
        # Prepare context for evaluation
        tool_summary = state.get_tool_call_summary()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""
ORIGINAL GOAL: {state.user_goal}
CURRENT PLAN: {state.current_plan}

EXECUTION PROGRESS:
Completed Steps: {len(state.completed_steps)}/{len(state.execution_steps)}
{chr(10).join(f"✓ {step}" for step in state.completed_steps)}

TOOL EXECUTION SUMMARY:
{tool_summary}

RECENT TOOL OUTPUTS:
{json.dumps(state.current_tool_outputs, indent=2) if state.current_tool_outputs else "No recent outputs"}

ERRORS (if any):
{chr(10).join(state.errors) if state.errors else "No errors"}

Please evaluate the current progress and decide what to do next.
"""}
        ]

        try:
            response, _ = await llm_router.generate_with_fallback(
                messages=messages,
                preferred_provider=state.selected_llm
            )

            evaluation = self._parse_evaluation_response(response)

            # Update state based on evaluation
            next_action = evaluation.get("next_action", "continue")

            if next_action == "complete":
                final_response = evaluation.get("response", "Task completed successfully.")
                state.mark_complete(final_response)
            elif next_action == "user_input":
                state.needs_user_input = True
            elif next_action == "error":
                error_msg = evaluation.get("response", "An error occurred during execution.")
                state.add_error(error_msg)

            return evaluation

        except Exception as e:
            error_msg = f"Failed to evaluate progress: {str(e)}"
            state.add_error(error_msg)
            return {
                "evaluation": "Unable to evaluate progress",
                "next_action": "error",
                "reasoning": "LLM evaluation failed",
                "response": error_msg
            }

    async def select_next_tool(self, state: AgentState) -> Optional[Dict[str, Any]]:
        """Select the next tool to execute based on current state."""
        if state.is_complete or not state.execution_steps:
            return None

        # Find the next uncompleted step
        next_step_index = len(state.completed_steps)
        if next_step_index >= len(state.execution_steps):
            return None

        # Check if we have original plan steps to determine action type
        if state.original_plan_steps and next_step_index < len(state.original_plan_steps):
            original_step = state.original_plan_steps[next_step_index]

            # If this is a prompt_user action, return prompt information
            if original_step.get("action") == "prompt_user":
                return {
                    "action": "prompt_user",
                    "prompt": original_step.get("prompt", "Please provide the required information."),
                    "description": original_step.get("description", "Requesting user input"),
                    "reasoning": "User input is required to proceed"
                }

        next_step = state.execution_steps[next_step_index]

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""
CURRENT STEP: {next_step}
AVAILABLE TOOLS: {tool_executor.get_tools_description()}

CONTEXT:
- Goal: {state.user_goal}
- Previous outputs: {json.dumps(state.current_tool_outputs, indent=2)}

Please specify exactly which tool to call and with what inputs to execute this step.
Respond with JSON: {{"tool_name": "name", "inputs": {{"key": "value"}}, "reasoning": "why"}}
"""}
        ]

        try:
            response, _ = await llm_router.generate_with_fallback(
                messages=messages,
                preferred_provider=state.selected_llm
            )

            tool_selection = self._parse_tool_selection(response)
            return tool_selection

        except Exception as e:
            state.add_error(f"Failed to select next tool: {str(e)}")
            return None

    async def generate_final_response(self, state: AgentState) -> str:
        """Generate a final response to the user based on all results."""
        if state.final_response:
            return state.final_response

        messages = [
            {"role": "system", "content": """You are an autonomous agent providing a final response to the user. 
Summarize what was accomplished, highlight key results, and provide a clear, helpful response.

IMPORTANT: If the user asked for counts, calculations, or data analysis:
- Process the retrieved data directly in your response
- Count items, calculate totals, or perform analysis as needed
- Provide specific numbers and clear answers
- Don't mention missing tools - just process the available data

For example, if asked "How many books in total" and you retrieved a list of books, count them and provide the exact number."""},
            {"role": "user", "content": f"""
USER'S ORIGINAL GOAL: {state.user_goal}

EXECUTION SUMMARY:
- Steps completed: {len(state.completed_steps)}
- Tools used: {len(state.tool_calls)}
- Errors encountered: {len(state.errors)}

TOOL RESULTS:
{self._format_tool_results(state)}

ERRORS (if any):
{chr(10).join(state.errors) if state.errors else "No errors"}

Please provide a comprehensive final response to the user about what was accomplished.
"""}
        ]

        try:
            response, _ = await llm_router.generate_with_fallback(
                messages=messages,
                preferred_provider=state.selected_llm
            )

            return response.strip()

        except Exception as e:
            return f"Task execution completed with some issues. Error generating final response: {str(e)}"

    def _parse_plan_response(self, response: str) -> Dict[str, Any]:
        """Parse the LLM's plan response."""
        try:
            # Try to extract JSON from the response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                # Fallback: create a simple plan from text
                return {
                    "analysis": response[:200] + "..." if len(response) > 200 else response,
                    "plan": [],
                    "reasoning": "Unable to parse structured plan from response"
                }

        except json.JSONDecodeError:
            return {
                "analysis": response[:200] + "..." if len(response) > 200 else response,
                "plan": [],
                "reasoning": "Invalid JSON in plan response"
            }

    def _parse_evaluation_response(self, response: str) -> Dict[str, Any]:
        """Parse the LLM's evaluation response."""
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                # Fallback evaluation
                return {
                    "evaluation": response[:200] + "..." if len(response) > 200 else response,
                    "next_action": "continue",
                    "reasoning": "Unable to parse structured evaluation",
                    "response": response
                }

        except json.JSONDecodeError:
            return {
                "evaluation": response[:200] + "..." if len(response) > 200 else response,
                "next_action": "continue",
                "reasoning": "Invalid JSON in evaluation response",
                "response": response
            }

    def _parse_tool_selection(self, response: str) -> Dict[str, Any]:
        """Parse the LLM's tool selection response."""
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            else:
                return {"error": "Unable to parse tool selection"}

        except json.JSONDecodeError:
            return {"error": "Invalid JSON in tool selection response"}

    def _format_tool_results(self, state: AgentState) -> str:
        """Format tool results for final response generation."""
        if not state.tool_calls:
            return "No tools were executed."

        results = []
        for tool_call in state.tool_calls:
            result_str = f"Tool: {tool_call.name}"
            if tool_call.output:
                # For book-related tools, don't truncate the output to allow full data processing
                output_str = str(tool_call.output)
                if tool_call.name in ['get_all_books', 'search_books', 'get_book_by_id', 'list_books']:
                    # Don't truncate book data - let the LLM process the full dataset
                    result_str += f"\nResult: {output_str}"
                else:
                    # For other tools, still apply reasonable truncation
                    if len(output_str) > 1000:
                        output_str = output_str[:1000] + "..."
                    result_str += f"\nResult: {output_str}"
            elif tool_call.error:
                result_str += f"\nError: {tool_call.error}"
            results.append(result_str)

        return "\n\n".join(results)

# Global planner instance
planner = AgentPlanner()
