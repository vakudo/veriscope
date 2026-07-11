import json

from app.calibration import load_calibration


def write_calibration(tmp_path, payload):
    file = tmp_path / "calibration.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    return str(file)


def test_small_buckets_are_dropped(tmp_path):
    path = write_calibration(
        tmp_path,
        {
            "supported": {"correct": 4, "total": 4},
            "refuted": {"correct": 90, "total": 100},
        },
    )
    accuracy = load_calibration(path, min_samples=20)
    assert accuracy == {"refuted": 0.9}


def test_threshold_is_configurable(tmp_path):
    path = write_calibration(tmp_path, {"supported": {"correct": 4, "total": 4}})
    assert load_calibration(path, min_samples=4) == {"supported": 1.0}


def test_missing_file_gives_empty():
    assert load_calibration("no_such_file.json") == {}


def test_invalid_json_gives_empty(tmp_path):
    file = tmp_path / "calibration.json"
    file.write_text("not json", encoding="utf-8")
    assert load_calibration(str(file)) == {}


def test_malformed_buckets_are_skipped(tmp_path):
    path = write_calibration(
        tmp_path,
        {"supported": "garbage", "refuted": {"correct": 25, "total": 25}},
    )
    assert load_calibration(path, min_samples=20) == {"refuted": 1.0}
