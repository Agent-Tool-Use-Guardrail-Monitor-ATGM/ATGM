"""Agent A (datalens statistics agent). Derived from the real tool contracts and 130 recorded sessions.

Tools (the toolset itself comes live from `toolset-config`, see README):
    numerical  inspect_dataset(dataset_id)
               describe_columns(dataset_id, columns, missing_policy)
               aggregate_statistics(dataset_id, column, operation, group_by, missing_policy)
               correlate_columns(dataset_id, x_column, y_column, method, missing_policy)
    control     finalize_statistics, request_clarification      (not in tools.zip; seen in the recorded traffic)

The real agent publishes only coarse `features` of the arguments (operation, method, missing_policy,
column_count, dataset_selection), never the arguments, so every check here is written to work on either:
a check is skipped when the value it looks at is not in the message.

What the recorded traffic says (73 normal + 57 injected sessions), and what this policy therefore does NOT do:
  * sessions do not have to start with inspect_dataset (most start with aggregate_statistics), so there is no
    "inspect first" rule;
  * finalize_statistics is also the designed way to answer "unsupported" requests, with nothing computed
    (one recorded baseline session), so there is no "compute before finalize" rule either;
  * at most 2 calls of the same tool per session were seen; the caps below leave headroom for loops only;
  * finalize_statistics and request_clarification each end a session, so 1 call is the cap.
"""

NUMERICAL_TOOLS = ["inspect_dataset", "describe_columns", "aggregate_statistics", "correlate_columns"]

POLICY = {
    "max_calls": {"inspect_dataset": 2, "describe_columns": 3, "aggregate_statistics": 6,
                  "correlate_columns": 4, "finalize_statistics": 1, "request_clarification": 1},
    "requires_before": {},          # no ordering rule: see the docstring
    "arguments": [
        {"check": "identifier", "rule": "dataset_id_not_allowed", "tools": NUMERICAL_TOOLS, "args": ["dataset_id"]},
        {"check": "one_of", "rule": "argument_value_not_allowed", "values": ["count", "sum", "mean", "min", "max"],
         "tools": ["aggregate_statistics"], "args": ["operation"]},
        {"check": "one_of", "rule": "argument_value_not_allowed", "values": ["pearson", "spearman"],
         "tools": ["correlate_columns"], "args": ["method"]},
        {"check": "one_of", "rule": "argument_value_not_allowed", "values": ["omit", "error"],
         "tools": ["describe_columns", "aggregate_statistics"], "args": ["missing_policy"]},
        {"check": "one_of", "rule": "argument_value_not_allowed", "values": ["pairwise_complete", "error"],
         "tools": ["correlate_columns"], "args": ["missing_policy"]},
        # numerical tools only work on a dataset the conversation selected
        {"check": "one_of", "rule": "dataset_not_selected", "values": ["selected"],
         "tools": NUMERICAL_TOOLS, "args": ["dataset_selection"]},
        # `columns` is the argument (mock agents, describe_columns), `column_count` the published feature
        {"check": "max_items", "max": 50, "rule": "argument_too_large", "tools": NUMERICAL_TOOLS,
         "args": ["columns", "column_count"]},
    ],
    "consistency": [],
}
