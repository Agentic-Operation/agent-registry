import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REG = Path(__file__).resolve().parents[1] / "src" / "registry" / "registry.py"
CARD = Path("/tmp/card-example.json")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    # fetch the worked example card from the discovery-card repo (public)
    import urllib.request as u
    u.urlretrieve("https://raw.githubusercontent.com/Agentic-Operation/agent-discovery-card/main/examples/loyalty-agent/card.json", CARD)
    store = tmp_path_factory.mktemp("store") / "cards.json"
    proc = subprocess.Popen([sys.executable, str(REG), "--port", "8499", "--store", str(store)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    yield "http://localhost:8499"
    proc.terminate()


def post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req)


def test_register_search_verify_environments(server):
    card = json.load(open(CARD))
    r = post(f"{server}/v1/cards", card)
    assert r.status == 201
    with urllib.request.urlopen(f"{server}/v1/cards?skill_id=TMF-OASF%202046") as r:
        hits = json.loads(r.read())
    assert len(hits) == 1 and hits[0]["id"] == card["id"]
    r = post(f"{server}/v1/cards/{card['id']}/verify", {})
    assert json.loads(r.read())["verified"] is True
    with urllib.request.urlopen(f"{server}/v1/cards/{card['id']}/environments") as r:
        envs = json.loads(r.read())
    assert {e["environment"] for e in envs} == {"dev", "stage", "prod"}
