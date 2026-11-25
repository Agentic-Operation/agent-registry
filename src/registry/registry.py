#!/usr/bin/env python3
"""Agent Card Registry — reference implementation of api/openapi/registry-api.yaml (Spec-445).

Stdlib-only HTTP service. Persistence: in-memory + optional JSON file (--store).
Endpoints (base /v1):
  POST   /cards                      register (validates via card_validate; 201 / 422)
  GET    /cards                      search (skill_id, source_taxonomy, autonomy_level, impactRadius, ...)
  GET    /cards/{id}                 latest card
  GET    /cards/{id}/versions/{v}    specific version
  POST   /cards/{id}/verify          integrity check (CID format + integrity_wrapper + optional cosign)
  GET    /cards/{id}/environments     environment-instances list
  PUT    /cards/{id}/environments/{env}   register/update env instance (rollout controller calls this)
  GET    /.well-known/woa.json       WoA discovery
"""
import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_conf = os.environ.get("AGENT_CONFORMANCE", str(Path(__file__).resolve().parents[2] / "conformance"))
sys.path.insert(0, os.path.join(_conf, "validators"))
import card_validate  # noqa: E402  (from agent-conformance checkout)

CID = re.compile(r"^sha256:[a-f0-9]{64}$")


class Store:
    def __init__(self, path=None):
        self.cards = {}  # id -> {version -> card}
        self.path = path
        if path and Path(path).exists():
            for c in json.load(open(path)):
                self.cards.setdefault(c["id"], {})[c["version"]] = c

    def put(self, card):
        self.cards.setdefault(card["id"], {})[card["version"]] = card
        if self.path:
            json.dump([c for vs in self.cards.values() for c in vs.values()], open(self.path, "w"), indent=2)

    def latest(self, cid):
        vs = self.cards.get(cid)
        return vs[max(vs)] if vs else None


def lint_card(card):
    errors = []
    card_validate.validate(card, errors)
    return errors


def env_instances(card):
    for e in card.get("extensions", []):
        if "environment-instances" in (e.get("uri") or ""):
            return e["params"].get("environments", [])
    return []


class Handler(BaseHTTPRequestHandler):
    store: Store = None  # set in main

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path.strip("/").split("/")
        q = parse_qs(u.query)
        if u.path.startswith("/.well-known/woa.json"):
            agent = q.get("agent", [None])[0]
            card = self.store.latest(agent) if agent else None
            return self._send(200, card) if card else self._send(404, {"error": "not found"})
        if p[:2] == ["v1", "cards"] and len(p) == 2:
            out = []
            for cid, vs in self.store.cards.items():
                c = vs[max(vs)]
                if "skill_id" in q and not any(s["id"] == q["skill_id"][0] for s in c.get("skills", [])):
                    continue
                if "autonomy_level" in q and c.get("classification", {}).get("autonomy_level") != q["autonomy_level"][0]:
                    continue
                if "impactRadius" in q and c.get("impactRadius") != q["impactRadius"][0]:
                    continue
                if "deploymentStatus" in q and c.get("deploymentStatus") != q["deploymentStatus"][0]:
                    continue
                out.append(c)
            return self._send(200, out)
        if len(p) >= 3 and p[:2] == ["v1", "cards"]:
            card = self.store.latest(p[2])
            if not card:
                return self._send(404, {"error": "not found"})
            if len(p) == 5 and p[3] == "versions":
                card = self.store.cards[p[2]].get(p[4])
                return self._send(200, card) if card else self._send(404, {"error": "version not found"})
            if len(p) == 4 and p[3] == "environments":
                return self._send(200, env_instances(card))
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path.strip("/").split("/")
        if p == ["v1", "cards"]:
            card = self._body()
            errors = lint_card(card)
            if errors:
                return self._send(422, {"violations": errors})
            self.store.put(card)
            return self._send(201, {"id": card["id"], "version": card["version"], "status": "registered"})
        if len(p) == 4 and p[:2] == ["v1", "cards"] and p[3] == "verify":
            card = self.store.latest(p[2])
            if not card:
                return self._send(404, {"error": "not found"})
            errs = []
            if not CID.match(card.get("content_identifier_cid", "")):
                errs.append("bad content_identifier_cid")
            iw = card.get("integrity_wrapper")
            if not iw or not all(iw.get(k) for k in ("signature_type", "issuer", "transparency_log")):
                errs.append("integrity_wrapper incomplete")
            # real signature verification happens at agent startup (stage 3, verify_integrity.py);
            # cosign verify-blob can be plugged in here when available.
            return self._send(200 if not errs else 422, {"verified": not errs, "errors": errs})
        return self._send(404, {"error": "not found"})

    def do_PUT(self):
        u = urlparse(self.path)
        p = u.path.strip("/").split("/")
        if len(p) == 5 and p[:2] == ["v1", "cards"] and p[3] == "environments":
            card = self.store.latest(p[2])
            if not card:
                return self._send(404, {"error": "not found"})
            inst = self._body()
            for k in ("instance_id", "deployed_version", "artifact_cid", "health", "rollout_state"):
                if k not in inst:
                    return self._send(422, {"error": f"missing {k}"})
            if not CID.match(inst["artifact_cid"]):
                return self._send(422, {"error": "bad artifact_cid"})
            inst["environment"] = p[4]
            for e in card.setdefault("extensions", []):
                if "environment-instances" in (e.get("uri") or ""):
                    envs = e["params"].setdefault("environments", [])
                    envs[:] = [x for x in envs if x.get("environment") != p[4]]
                    envs.append(inst)
                    self.store.put(card)
                    return self._send(200, {"updated": p[4]})
            return self._send(422, {"error": "card lacks environment-instances extension"})
        return self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--store", default=None, help="JSON file for persistence")
    a = ap.parse_args()
    Handler.store = Store(a.store)
    print(f"registry listening on :{a.port}")
    HTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
