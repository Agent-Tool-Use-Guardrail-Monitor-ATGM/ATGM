"""Integrated SpaceSaving± frequent-item summary."""

from dataclasses import dataclass


@dataclass
class Counter:
    """Insertion and deletion estimates for one monitored item."""

    insert_count: int
    delete_count: int = 0

    @property
    def estimate(self) -> int:
        return self.insert_count - self.delete_count


class IntegratedSpaceSaving:
    """Bounded-memory frequent-item summary with deletions."""

    def __init__(self, capacity: int = 100) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")

        self.capacity = capacity
        self.counters: dict[str, Counter] = {}
        self.total_insertions = 0
        self.total_deletions = 0

    def insert(self, item: str) -> None:
        """Process one insertion."""
        if not item:
            raise ValueError("item cannot be empty")

        self.total_insertions += 1

        if item in self.counters:
            self.counters[item].insert_count += 1
            return

        if len(self.counters) < self.capacity:
            self.counters[item] = Counter(insert_count=1)
            return

        minimum_item = min(
            self.counters,
            key=lambda key: self.counters[key].insert_count,
        )
        minimum_count = self.counters[minimum_item].insert_count

        del self.counters[minimum_item]

        self.counters[item] = Counter(
            insert_count=minimum_count + 1,
            delete_count=0,
        )

    def delete(self, item: str) -> None:
        """Process one deletion of a previously inserted item."""
        if not item:
            raise ValueError("item cannot be empty")

        if item in self.counters:
            self.counters[item].delete_count += 1
            self.total_deletions += 1
            return

        if len(self.counters) == self.capacity:
            self.total_deletions += 1
            return

        raise ValueError(
            f"deletion received for an item that was never monitored: {item}"
        )

    def update(self, item: str, operation: str) -> None:
        """Apply an insertion or deletion."""
        if operation == "insert":
            self.insert(item)
        elif operation == "delete":
            self.delete(item)
        else:
            raise ValueError("operation must be 'insert' or 'delete'")

    def estimate(self, item: str) -> int:
        """Estimate an item's current frequency."""
        counter = self.counters.get(item)
        return counter.estimate if counter is not None else 0

    def top(self, limit: int = 10) -> list[dict]:
        """Return the highest estimated frequencies."""
        if limit < 1:
            raise ValueError("limit must be at least 1")

        ranked = sorted(
            self.counters.items(),
            key=lambda pair: pair[1].estimate,
            reverse=True,
        )

        return [
            {"item": item, "count": counter.estimate}
            for item, counter in ranked[:limit]
            if counter.estimate > 0
        ]
