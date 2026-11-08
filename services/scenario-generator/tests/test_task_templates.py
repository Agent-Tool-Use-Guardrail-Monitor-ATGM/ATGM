import random

from domain.task_templates import get_agent_b_templates, render

def test_render_fills_placeholders_and_hides_label():
    for template in get_agent_b_templates():
        task, truth = render(template, random.Random(1))
        assert "{" not in task["user_input"]
        assert "adversarial" not in task["scenario_id"]
        assert task["scenario_id"] == truth["scenario_id"]
        assert "category" not in task  # the label never goes to the agent