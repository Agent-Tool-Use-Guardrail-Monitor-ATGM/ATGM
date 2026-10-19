# Stream processing (placeholder)

One subfolder per member's stream mining stages, e.g. `stream-processing/online-iforest/`.

Each stage reads from Kafka topics, runs its algorithm, and writes results to `flags`, `alerts` or its own topic. Add new topics to `infra/kafka/topics.txt`.

Suggested layout (ports & adapters):

```
domain/     the algorithm itself; plain Python, no Kafka, so it can be tested and replayed on datasets
adapters/   Kafka consumer/producer
main.py
Dockerfile
```
