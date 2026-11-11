from online_forest.detector import OnlineForestDetector


def test_detector_processes_events():
    detector = OnlineForestDetector()

    event = {
        "duration_ms": 120,
        "arguments": {"expression": "10 + 20"},
        "session_call_index": 1,
        "time_since_previous_call_ms": 0,
        "success": True,
    }

    result = detector.process(event)

    assert "anomaly_score" in result
    assert "is_anomaly" in result
    assert result["samples_seen"] == 1
    assert isinstance(result["anomaly_score"], float)


def test_detector_learns_incrementally():
    detector = OnlineForestDetector()

    for i in range(10):
        event = {
            "duration_ms": 100 + i,
            "arguments": {"value": i},
            "session_call_index": i,
            "time_since_previous_call_ms": 100,
            "success": True,
        }

        detector.process(event)

    assert detector.samples_seen == 10

def test_detector_scores_different_events():
    normal_event = {
        "duration_ms": 100,
        "arguments": {"value": 10},
        "session_call_index": 1,
        "time_since_previous_call_ms": 100,
        "success": True,
    }

    unusual_event = {
        "duration_ms": 100000,
        "arguments": {"value": "X" * 10000},
        "session_call_index": 5000,
        "time_since_previous_call_ms": 999999,
        "success": False,
    }

    normal_detector = OnlineForestDetector()
    unusual_detector = OnlineForestDetector()

    for _ in range(200):
        normal_detector.process(normal_event)
        unusual_detector.process(normal_event)

    normal_result = normal_detector.process(normal_event)
    unusual_result = unusual_detector.process(unusual_event)

    print("Normal score:", normal_result["anomaly_score"])
    print("Unusual score:", unusual_result["anomaly_score"])

def test_anomaly_threshold():
    detector = OnlineForestDetector()

    normal_event = {
        "duration_ms": 100,
        "arguments": {"value": 10},
        "session_call_index": 1,
        "time_since_previous_call_ms": 100,
        "success": True,
    }

    unusual_event = {
        "duration_ms": 100000,
        "arguments": {"value": "X" * 10000},
        "session_call_index": 5000,
        "time_since_previous_call_ms": 999999,
        "success": False,
    }

    for _ in range(200):
        detector.process(normal_event)

    normal_anomalies = 0
    unusual_anomalies = 0

    for _ in range(20):
        result = detector.process(normal_event)
        print(f"Normal score: {result['anomaly_score']:.4f}")

        if result["is_anomaly"]:
            normal_anomalies += 1

    for _ in range(20):
        result = detector.process(unusual_event)
        print(f"Unusual score: {result['anomaly_score']:.4f}")

        if result["is_anomaly"]:
            unusual_anomalies += 1

    print("Normal anomalies:", normal_anomalies, "/ 20")
    print("Unusual anomalies:", unusual_anomalies, "/ 20")