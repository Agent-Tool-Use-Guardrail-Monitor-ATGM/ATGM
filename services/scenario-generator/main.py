from domain.task_templates import (
    get_agent_b_templates,
    render,
)
from adapters.ground_truth_store import (
    GroundTruthStore,
    ScenarioResultStore,
)
from adapters.agent_client import AgentBClient
import os

def run_scenarios(total: int = 30):

    store = GroundTruthStore()
    result_store = ScenarioResultStore()
    client = AgentBClient()

    templates = get_agent_b_templates()

    for i in range(total):

        template = templates[i % len(templates)]

        # 1. Generate scenario
        task, truth = render(template)

        # 2. Save ground truth separately
        store.save(truth)

        try:
            # 3. Send task to agent
            result = client.send_task(
                task["agent"],
                task["user_input"]
            )

            # 4. Collect result
            result_record = {
                "scenario_id": task["scenario_id"],
                "called_tools": result["called_tools"],
                "tool_outputs": result["tool_outputs"],
                "final_response": result["final_response"],
                "execution_status": "success",
                "error_message": None,
            }

        except Exception as exc:
            result_record = {
                "scenario_id": task["scenario_id"],
                "called_tools": [],
                "tool_outputs": [],
                "final_response": "",
                "execution_status": "failed",
                "error_message": str(exc),
            }

        # 5. Save execution result
        result_store.save(result_record)

        print(f"Scenario {i + 1}/{total}")
        print("ID:", task["scenario_id"])
        print("Status:", result_record["execution_status"])
        
if __name__ == "__main__":
    total = int(os.getenv("SCENARIO_TOTAL", "30"))
    run_scenarios(total)