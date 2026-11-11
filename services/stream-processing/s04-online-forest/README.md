# Online Forest stream Processing

## Overview

The Online Forest component implements an incremental anomaly detection pipeline for incoming tool-call events using the **Online Isolation Forest** algorithm provided by CapyMOA.

It continuously consumes events from Kafka, extracts numerical features, updates the anomaly detection model and calculates an anomaly score for each event.

The component is designed to process streaming data rather than waiting for a complete dataset.

## Architecture

The processing pipeline consists of the following steps:

1. **Kafka Consumer** - Reads incoming events from Kafka topics.
2. **Event Parsing** - Decodes incoming JSON messages.
3. **Feature Extraction** - Converts tool-call events into numerical feature vectors.
4. **Online Isolation Forest** - Scores incoming events and incrementally trains the model.
5. **Anomaly Detection** - Compares anomaly scores against a configurable threshold.
6. **Logging** -Logs processing results, including anomaly scores and detection decisions.

### Data flow

```text
Agent / Event Producer
        |
        v
      Kafka
        |
        v
  Kafka Consumer
        |
        v
  JSON Event Parsing
        |
        v
  Feature Extraction
        |
        v
 Online Isolation Forest
        |
        v
  Anomaly Detection
        |
        v
      Logging
```

## Kafka Input

The consumer subscribes to the following topics:

- `tool-calls.A`
- `tool-calls.B`

Each message is expected to contain a JSON object representing a tool-call event.

Example:

```json
{
  "duration_ms": 120,
  "arguments": {
    "query": "test"
  },
  "session_call_index": 1,
  "time_since_previous_call_ms": 1000,
  "success": true
}
```

## Feature Extraction

The following features are extracted from each event:

| Feature | Description |
|---|---|
| `duration_ms` | Tool-call execution duration |
| `argument_count` | Number of arguments |
| `argument_length` | Length of the serialized arguments |
| `session_call_index` | Position of the call in the session |
| `time_since_previous_call_ms` | Time elapsed since the previous call |
| `success` | Whether the tool-call succeeded |

All features are converted into numerical values before being passed to the model.

## Online Isolation Forest

The component uses CapyMOA's `OnlineIsolationForest` implementation.

Current configuration:

| Parameter | Value |
|---|---:|
| Number of trees | 25 |
| Window size | 512 |
| Maximum leaf samples | 32 |
| Random seed | 42 |
| Anomaly threshold | 0.22 |
| Warm-up samples | 128 |

The model processes events incrementally:

1. Extract features from the incoming event.
2. Calculate the anomaly score using the current model.
3. Train the model with the incoming event.
4. Increment the processed sample counter.
5. Mark the event as anomalous if the warm-up period has passed and the score reaches the configured threshold.

Scoring is performed **before training** on each event.

The threshold is currently preliminary and should be calibrated using representative data.

## Output

For every successfully processed event, the consumer logs:

- Kafka topic
- Partition
- Message offset
- Number of samples processed
- Anomaly score
- Anomaly detection result

Example log:

```text
INFO:__main__:Topic=tool-calls.A partition=2 offset=64 samples_seen=201 score=0.308477 anomaly=True
```

The current implementation logs detection results locally. Publishing scores to the `scores` topic or detected anomalies to the `alerts` topic is not yet implemented and requires agreement on the expected output schema.

## Installation

Python 3.11 is recommended.

Create and activate a virtual environment:

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
```

Install dependencies:

```bash
pip install --upgrade pip
pip install -e .
```

## Running Locally

Make sure the Kafka infrastructure is running and accessible at `localhost:29092`.

Run the consumer from the component directory:

```bash
PYTHONPATH=src python -m online_forest.consumer
```

The consumer will subscribe to `tool-calls.A` and `tool-calls.B` and start processing incoming events.

## Configuration

Model parameters are defined in:

```text
src/online_forest/config.py
```

Kafka connection settings can be configured using environment variables:

| Variable | Default |
|---|---|
| `KAFKA_BOOTSTRAP` | `localhost:29092` |
| `KAFKA_GROUP_ID` | `online-forest-consumer` |

Example:

```bash
export KAFKA_BOOTSTRAP=localhost:29092
export KAFKA_GROUP_ID=online-forest-consumer
```

## Testing

Run the unit tests:

```bash
PYTHONPATH=src pytest
```

The component has also been tested with synthetic Kafka events.

The integration test demonstrated that:

- Normal events can be processed continuously.
- The model learns incrementally from incoming events.
- Unusual synthetic events can receive higher anomaly scores.
- An event with an anomaly score of `0.308477` was successfully classified as anomalous using the configured threshold of `0.22`.

These results demonstrate basic functionality on synthetic data and do not represent production detection accuracy.

## Docker

Build the Docker image:

```bash
docker build -t atgm-online-forest .
```

Run the container:

```bash
docker run --rm \
  --network <kafka-network> \
  -e KAFKA_BOOTSTRAP=kafka:9092 \
  -e KAFKA_GROUP_ID=online-forest-consumer \
  atgm-online-forest
```
