
from agent_b.domain.agent import create_agent_b


class AgentBClient:

    def __init__(self):
        self.agent = create_agent_b()

    def send_task(self, agent: str, task: str) -> dict:

        if agent != "B":
            raise ValueError("AgentBClient only supports Agent B.")

        if not task.strip():
            raise ValueError("Task cannot be empty.")

        result = self.agent.invoke({
            "messages": [{
                "role": "user",
                "content": task
            }]
        })

        messages = result["messages"]

        called_tools = []
        tool_outputs = []
        final_response = ""

        for message in messages:

            # Actual tool execution results
            if getattr(message, "type", None) == "tool":
                tool_name = getattr(message, "name", None)

                if tool_name:
                    called_tools.append(tool_name)

                tool_outputs.append({
                    "tool_name": tool_name,
                    "tool_call_id": getattr(message, "tool_call_id", None),
                    "output": str(message.content)
                })

            # Final AI response (not a tool call)
            elif (
                getattr(message, "type", None) == "ai"
                and not getattr(message, "tool_calls", None)
            ):
                content = message.content
                final_response = (
                    content if isinstance(content, str) else str(content)
                )

        return {
            "messages": messages,
            "called_tools": called_tools,
            "tool_outputs": tool_outputs,
            "final_response": final_response
        }
