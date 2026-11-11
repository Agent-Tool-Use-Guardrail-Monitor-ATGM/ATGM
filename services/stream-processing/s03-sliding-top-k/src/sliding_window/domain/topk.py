from collections import Counter, defaultdict, deque


class WindowNode:
    """One node: item counts over the last `units` time slots."""

    def __init__(self, slot_seconds, units):
        self.slot_seconds = slot_seconds
        self.units = units
        self.slots = deque()               # (slot number, Counter of the items in that slot)
        self.counts = Counter()            # item counts in the whole window
        self.revision = defaultdict(float) # revision factor per item, set by the coordinator
        self.updates = 0                   # arrivals + expirations, for the naive cost

    def add(self, item, timestamp):
        self.slide(timestamp)
        slot = int(timestamp // self.slot_seconds)
        if not self.slots or self.slots[-1][0] < slot:
            self.slots.append((slot, Counter()))
        self.slots[-1][1][item] += 1
        self.counts[item] += 1
        self.updates += 1

    def slide(self, timestamp):
        """Remove slots that are older than the window."""
        current_slot = int(timestamp // self.slot_seconds)
        while self.slots and self.slots[0][0] <= current_slot - self.units:
            _, old_counts = self.slots.popleft()
            self.counts.subtract(old_counts)
            self.counts += Counter()       # removes items whose count dropped to 0
            self.updates += sum(old_counts.values())

    def value(self, item):
        return self.counts[item] + self.revision[item]

    def agrees_with(self, top, tolerance):
        """Local check: every top-k item must still beat every other item on this node."""
        if not top:
            return True
        weakest_top = min(self.value(item) for item in top)
        others = (set(self.counts) | set(self.revision)) - top
        return all(self.value(item) <= weakest_top + tolerance for item in others)


class TopKMonitor:
    def __init__(self, k=3, nodes=3, slot_seconds=30.0, units=20, epsilon=0.0):
        self.k = k
        self.epsilon = epsilon
        self.nodes = [WindowNode(slot_seconds, units) for _ in range(nodes)]
        self.top = set()
        self.messages = 0                  # node <-> coordinator messages
        self.resolutions = 0

    def add(self, node_number, item, timestamp):
        """A new item arrives at one node. Returns (before, after) if the top-k changed."""
        self.nodes[node_number].add(item, timestamp)
        return self.advance(timestamp)

    def advance(self, timestamp):
        """Let time pass, then check every node. Returns (before, after) if the top-k changed."""
        for node in self.nodes:
            node.slide(timestamp)
        tolerance = self.epsilon / len(self.nodes)
        alerts = [node for node in self.nodes if not node.agrees_with(self.top, tolerance)]
        top_not_full = len(self.top) < self.k and len(self.all_items()) > len(self.top)
        if not alerts and not top_not_full:
            return None
        before = set(self.top)
        self.messages += len(alerts)
        self._resolve()
        return (before, set(self.top)) if before != self.top else None

    def _resolve(self):
        """Global resolution: collect all counts, pick the new top-k, send new revision factors."""
        self.messages += 3 * len(self.nodes)          # request, replies, new factors
        self.resolutions += 1
        items = self.all_items()
        self.top = set(sorted(items, key=lambda item: (-self.total(item), item))[:self.k])
        # every node gets the same value for an item: its global count / number of nodes,
        # so all nodes rank items like the global top-k; the factors add up to 0 per item
        for item in items:
            fair_share = self.total(item) / len(self.nodes)
            for node in self.nodes:
                node.revision[item] = fair_share - node.counts[item]
        for node in self.nodes:                       # forget items that left every window
            for item in set(node.revision) - items:
                del node.revision[item]

    def total(self, item):
        """Exact count over all nodes."""
        return sum(node.counts[item] for node in self.nodes)

    def all_items(self):
        return set().union(*(node.counts for node in self.nodes))

    def ranking(self):
        """Current top-k with exact counts, highest first."""
        ranked = sorted(((item, self.total(item)) for item in self.top), key=lambda pair: (-pair[1], pair[0]))
        return [pair for pair in ranked if pair[1] > 0]

    @property
    def naive_messages(self):
        """Cost if every arrival and every expiry were sent to the coordinator."""
        return sum(node.updates for node in self.nodes)