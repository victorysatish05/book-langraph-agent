from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum

class LLMProvider(str, Enum):
    """Supported LLM providers."""
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"

class ToolCall(BaseModel):
    """Represents a tool call made by the agent."""
    name: str
    endpoint: str
    input_data: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None

class ToolMetadata(BaseModel):
    """Metadata for an available tool from MCP server."""
    name: str
    description: str
    endpoint: str
    input_schema: Dict[str, Any]

class AgentMessage(BaseModel):
    """Represents a message in the agent's conversation."""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: Optional[str] = None

class AgentState(BaseModel):
    """State maintained throughout the agent's execution."""

    # User input and goal
    user_goal: str = Field(description="The user's original goal or task")
    user_message: str = Field(description="The user's current message")

    # LLM configuration
    selected_llm: LLMProvider = Field(default=LLMProvider.GEMINI, description="Selected LLM provider")

    # Conversation history
    messages: List[AgentMessage] = Field(default_factory=list, description="Conversation history")

    # Tool-related state
    available_tools: List[ToolMetadata] = Field(default_factory=list, description="Tools discovered from MCP server")
    tool_calls: List[ToolCall] = Field(default_factory=list, description="History of tool calls made")
    current_tool_outputs: Dict[str, Any] = Field(default_factory=dict, description="Current tool execution results")

    # Planning and execution state
    current_plan: Optional[str] = Field(default=None, description="Current execution plan")
    execution_steps: List[str] = Field(default_factory=list, description="Steps in the current plan")
    completed_steps: List[str] = Field(default_factory=list, description="Completed execution steps")
    original_plan_steps: List[Dict[str, Any]] = Field(default_factory=list, description="Original plan steps with action types")

    # Control flow
    iteration_count: int = Field(default=0, description="Number of iterations completed")
    is_complete: bool = Field(default=False, description="Whether the task is complete")
    needs_user_input: bool = Field(default=False, description="Whether user input is needed")

    # Results and output
    intermediate_results: List[Dict[str, Any]] = Field(default_factory=list, description="Intermediate results from tool calls")
    final_response: Optional[str] = Field(default=None, description="Final response to the user")

    # Error handling
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")

    # Metadata
    session_id: Optional[str] = Field(default=None, description="Session identifier")
    start_time: Optional[str] = Field(default=None, description="When the session started")

    class Config:
        """Pydantic configuration."""
        use_enum_values = True
        arbitrary_types_allowed = True

    def add_message(self, role: str, content: str, timestamp: Optional[str] = None) -> None:
        """Add a message to the conversation history."""
        from datetime import datetime
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        message = AgentMessage(role=role, content=content, timestamp=timestamp)
        self.messages.append(message)

    def add_tool_call(self, name: str, endpoint: str, input_data: Dict[str, Any]) -> ToolCall:
        """Add a new tool call to the history."""
        from datetime import datetime

        tool_call = ToolCall(
            name=name,
            endpoint=endpoint,
            input_data=input_data,
            timestamp=datetime.now().isoformat()
        )
        self.tool_calls.append(tool_call)
        return tool_call

    def update_tool_call_result(self, tool_call: ToolCall, output: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        """Update a tool call with its result or error."""
        tool_call.output = output
        tool_call.error = error

    def add_error(self, error: str) -> None:
        """Add an error to the error list."""
        self.errors.append(error)

    def increment_iteration(self) -> None:
        """Increment the iteration counter."""
        self.iteration_count += 1

    def mark_complete(self, final_response: str) -> None:
        """Mark the task as complete with a final response."""
        self.is_complete = True
        self.final_response = final_response

    def get_conversation_context(self) -> str:
        """Get formatted conversation context for LLM."""
        context_parts = []
        for message in self.messages[-10:]:  # Last 10 messages for context
            context_parts.append(f"{message.role}: {message.content}")
        return "\n".join(context_parts)

    def get_tool_call_summary(self) -> str:
        """Get a summary of tool calls made."""
        if not self.tool_calls:
            return "No tools have been called yet."

        summary_parts = []
        for tool_call in self.tool_calls:
            status = "Success" if tool_call.output else "Error" if tool_call.error else "Pending"
            summary_parts.append(f"- {tool_call.name}: {status}")

        return "\n".join(summary_parts)
