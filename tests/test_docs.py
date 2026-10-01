"""The written instructions and the Postman collection stay pointed at this API."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLECTION = ROOT / "postman" / "fuel-route-api.postman_collection.json"


def test_the_collection_plans_trips_against_the_local_server():
    collection = json.loads(COLLECTION.read_text())

    assert collection["info"]["schema"].endswith("/v2.1.0/collection.json")
    variables = {item["key"]: item["value"] for item in collection["variable"]}
    assert variables["baseUrl"] == "http://localhost:8000"

    requests = _requests(collection["item"])
    assert len(requests) >= 2
    for request in requests:
        assert request["method"] == "POST"
        assert request["url"].endswith("/api/v1/route/")

    raw = COLLECTION.read_text()
    assert "30.2672" in raw  # Austin
    assert "-118.2437" in raw  # Los Angeles


def test_the_readme_states_what_a_reviewer_needs():
    readme = (ROOT / "README.md").read_text()

    assert "docker compose up --build" in readme
    assert "/api/v1/route/" in readme
    assert "/map/" in readme
    assert "500" in readme
    assert "10 mpg" in readme
    assert "full tank" in readme
    assert "postman/fuel-route-api.postman_collection.json" in readme
    assert "Loom" in readme


def _requests(items):
    found = []
    for item in items:
        if "request" in item:
            found.append(item["request"])
        found.extend(_requests(item.get("item", [])))
    return found
