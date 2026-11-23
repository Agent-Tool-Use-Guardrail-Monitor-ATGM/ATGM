from b3_markov.domain.sequences import END, START, UNK, max_run_length, transitions


def test_padding_order1():
    assert transitions(["a", "b"], 1) == [((START,), "a"), (("a",), "b"), (("b",), END)]


def test_padding_order2_has_t_plus_1_transitions():
    t = transitions(["a", "b", "c"], 2)
    assert len(t) == 4 and t[0] == ((START, START), "a") and t[-1] == (("b", "c"), END)


def test_empty_session_is_start_to_end():
    assert transitions([], 1) == [((START,), END)]
    assert transitions([], 2) == [((START, START), END)]


def test_unknown_tool_becomes_unk():
    assert transitions(["a", "x"], 1, {"a"}) == [((START,), "a"), (("a",), UNK), ((UNK,), END)]


def test_run_length():
    assert max_run_length([]) == 0 and max_run_length(["a", "a", "b", "a", "a", "a"]) == 3
