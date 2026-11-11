import random

from sliding_window.domain.topk import TopKMonitor, WindowNode


def random_stream(rng, count, items, flip_at=None, rate=20.0):
    """Zipf-like stream; at `flip_at` the popularity order reverses."""
    weights = [1 / (rank + 1) ** 1.2 for rank in range(len(items))]
    clock = 0.0
    for index in range(count):
        if index == flip_at:
            items = items[::-1]
        clock += rng.expovariate(rate)
        yield clock, rng.choices(items, weights)[0]


def top_is_correct(monitor):
    """Every top-k item is at least as frequent as any other item, within epsilon."""
    weakest = min(monitor.total(item) for item in monitor.top)
    others = monitor.all_items() - monitor.top
    return all(monitor.total(item) <= weakest + monitor.epsilon for item in others)


def test_old_slots_expire():
    node = WindowNode(slot_seconds=5, units=3)
    node.add("a", 0.0)
    node.add("a", 4.0)
    node.add("b", 7.0)
    assert node.counts["a"] == 2
    node.add("b", 15.1)                      # slot 3 starts: slot 0 (0-5 s) leaves the window
    assert node.counts["a"] == 0 and node.counts["b"] == 2


def test_top_k_is_always_correct():
    rng = random.Random(1)
    monitor = TopKMonitor(k=3, nodes=3, slot_seconds=2, units=10, epsilon=2.0)
    tools = [f"tool{number}" for number in range(15)]
    for clock, tool in random_stream(rng, 6000, tools, flip_at=3000):
        monitor.add(rng.randrange(3), tool, clock)
        assert top_is_correct(monitor)
    for item in monitor.all_items():             # revision factors add up to 0 for every item
        assert abs(sum(node.revision[item] for node in monitor.nodes)) < 1e-6


def test_uses_fewer_messages_than_naive():
    rng = random.Random(2)
    monitor = TopKMonitor(k=3, nodes=3, slot_seconds=2, units=10, epsilon=2.0)
    tools = [f"tool{number}" for number in range(15)]
    for clock, tool in random_stream(rng, 6000, tools):
        monitor.add(rng.randrange(3), tool, clock)
    assert monitor.messages < monitor.naive_messages


def test_burst_enters_top_k():
    monitor = TopKMonitor(k=2, nodes=2, slot_seconds=1, units=5)
    clock = 0.0
    for index in range(200):
        clock += 0.02
        monitor.add(index % 2, "find_contact" if index % 3 else "save_draft", clock)
    entered = set()
    for index in range(200):
        clock += 0.02
        change = monitor.add(index % 2, "send_email", clock)
        if change:
            before, after = change
            entered |= after - before
    assert "send_email" in entered and "send_email" in monitor.top