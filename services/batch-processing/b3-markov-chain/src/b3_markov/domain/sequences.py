"""Turns a tool-name sequence into (context, next) transitions of a given order."""
START, END, UNK, DELIM = "<START>", "<END>", "<UNK>", ">"


def transitions(tools: list[str], order: int, vocabulary: set[str] | None = None) -> list[tuple[tuple[str, ...], str]]:
    """Pads with `order` START tokens and one END token: a session of T calls gives T+1 transitions.

    Tools outside `vocabulary` (if given) become UNK.
    """
    seq = [tool if vocabulary is None or tool in vocabulary else UNK for tool in tools]
    padded = [START] * order + seq + [END]
    return [(tuple(padded[i - order:i]), padded[i]) for i in range(order, len(padded))]


def context_key(context: tuple[str, ...]) -> str:
    return DELIM.join(context)


def max_run_length(tools: list[str]) -> int:
    """Longest run of the same tool called repeatedly (draft_flooding etc.)."""
    best = run = 0
    previous = None
    for tool in tools:
        run = run + 1 if tool == previous else 1
        previous = tool
        best = max(best, run)
    return best
