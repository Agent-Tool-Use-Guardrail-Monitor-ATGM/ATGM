from agent_b.load_ground_truth import ground_truth_rows

SCENARIO = {"scenario_id": "s1", "agent": "B", "category": "adversarial", "attack_type": "unsafe_args",
            "expected_behavior": "save once", "policy": {"allowed_tools": ["save_draft"]},
            "reference_calls": [{"tool": "find_contact"}, {"tool": "save_draft"}]}


def test_category_comes_from_the_label():
    rows = ground_truth_rows([SCENARIO], [{"scenario_id": "s1", "label": "normal", "violated_rules": []}])
    assert rows[0]["category"] == "normal"
    assert rows[0]["attack_type"] is None
    assert rows[0]["expected_tools"] == ["find_contact", "save_draft"]


def test_attack_keeps_type_and_rules():
    label = {"scenario_id": "s1", "label": "adversarial", "violated_rules": ["secret_in_args"]}
    row = ground_truth_rows([SCENARIO], [label])[0]
    assert (row["category"], row["attack_type"], row["violated_rules"]) == \
           ("adversarial", "unsafe_args", ["secret_in_args"])


def test_scenario_without_label_is_skipped():
    assert ground_truth_rows([SCENARIO], []) == []