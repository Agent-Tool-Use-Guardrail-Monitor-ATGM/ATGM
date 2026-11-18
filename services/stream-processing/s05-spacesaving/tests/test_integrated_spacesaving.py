import pytest

from spacesaving.domain.integrated_spacesaving import IntegratedSpaceSaving


def test_insert_counts_repeated_items():
    sketch = IntegratedSpaceSaving(capacity=3)

    sketch.insert("tool:A")
    sketch.insert("tool:A")
    sketch.insert("tool:B")

    assert sketch.estimate("tool:A") == 2
    assert sketch.estimate("tool:B") == 1


def test_delete_reduces_estimated_count():
    sketch = IntegratedSpaceSaving(capacity=3)

    sketch.insert("tool:A")
    sketch.insert("tool:A")
    sketch.delete("tool:A")

    assert sketch.estimate("tool:A") == 1
    assert sketch.total_deletions == 1


def test_capacity_is_never_exceeded():
    sketch = IntegratedSpaceSaving(capacity=2)

    sketch.insert("tool:A")
    sketch.insert("tool:B")
    sketch.insert("tool:C")

    assert len(sketch.counters) == 2


def test_new_item_replaces_minimum_counter():
    sketch = IntegratedSpaceSaving(capacity=2)

    sketch.insert("tool:A")
    sketch.insert("tool:B")
    sketch.insert("tool:C")

    assert "tool:A" not in sketch.counters
    assert sketch.estimate("tool:C") == 2


def test_unmonitored_deletion_is_ignored_when_full():
    sketch = IntegratedSpaceSaving(capacity=2)

    sketch.insert("tool:A")
    sketch.insert("tool:B")
    sketch.insert("tool:C")

    sketch.delete("tool:unknown")

    assert len(sketch.counters) == 2
    assert sketch.total_deletions == 1


def test_unmonitored_deletion_raises_when_not_full():
    sketch = IntegratedSpaceSaving(capacity=3)

    sketch.insert("tool:A")

    with pytest.raises(ValueError):
        sketch.delete("tool:unknown")

    assert sketch.total_deletions == 0


def test_zero_capacity_is_rejected():
    with pytest.raises(ValueError):
        IntegratedSpaceSaving(capacity=0)


def test_empty_item_is_rejected():
    sketch = IntegratedSpaceSaving()

    with pytest.raises(ValueError):
        sketch.insert("")


def test_invalid_operation_is_rejected():
    sketch = IntegratedSpaceSaving()

    with pytest.raises(ValueError):
        sketch.update("tool:A", "invalid")


def test_top_returns_items_in_descending_count_order():
    sketch = IntegratedSpaceSaving(capacity=5)

    sketch.insert("tool:A")
    sketch.insert("tool:A")
    sketch.insert("tool:A")
    sketch.insert("tool:B")
    sketch.insert("tool:B")
    sketch.insert("tool:C")

    result = sketch.top(limit=3)

    assert result[0] == {"item": "tool:A", "count": 3}
    assert result[1] == {"item": "tool:B", "count": 2}
    assert result[2] == {"item": "tool:C", "count": 1}
