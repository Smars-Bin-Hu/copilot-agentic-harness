"""Which step of a connection broke (1.7.38): program, sign-in, account access, address.

A test of a connection ends in one of a few states (`core.connections.judge`). The person needs more: where to look. This module says which of four
steps is the first that failed, from what the harness can really tell, and one sentence for it. Where it cannot tell, it says so and marks no step.

  program   the test's program, or the program of the sign-in way (`auth.<way>.needs`), is on this computer
  signin    the sign-in is there: a tool signed in (`az`), or an account and a password saved or typed
  access    the system let that account in
  address   the system answered at the address (a certificate or a proxy can stop it)

A step is `ok`, `bad` (the first that broke), `unknown` (cannot tell) or `skip` (not looked at: an earlier step broke). A type may say, with `signin_lost`
(a pattern in the test's output), that the program found no sign-in before it asked the system; without it, a "not let in" of a tool sign-in is told as
"cannot tell which of sign-in and access".
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from . import messages

STEPS = ("program", "signin", "access", "address")
OK, BAD, UNKNOWN, SKIP = "ok", "bad", "unknown", "skip"
CERT = re.compile(r"certificate|CERTIFICATE_VERIFY|\bSSL\b|\bTLS\b|self[- ]signed|local issuer|not trusted", re.IGNORECASE)
NETWORK = re.compile(r"no such host|could not resolve|name or service not known|nodename nor servname|getaddrinfo|ENOTFOUND|connection refused|connection timed out|network is unreachable|no route to host|unable to open tcp|timed out", re.IGNORECASE)  # a program says so in its own words
PROXY = re.compile(r"\bproxy\b|\b407\b|tunnel", re.IGNORECASE)
ADDRESS_FIELDS = ("url", "host", "address", "server")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def where_of(kind: Dict[str, Any], server: Dict[str, Any]) -> str:
    """What the connection points at, as a person says it: `host:port`, else the fields but the address (`org · project`)."""
    values = {field: str(server.get(field) if server.get(field) not in (None, "") else spec.get("default", "")) for field, spec in (kind.get("fields") or {}).items() if isinstance(spec, dict)}
    if values.get("host"):
        return ":".join(item for item in (values["host"], values.get("port", "")) if item)
    rest = [value for field, value in values.items() if value and field not in ADDRESS_FIELDS]
    return " · ".join(rest) or next((value for value in values.values() if value), "") or str(server.get("label") or "")


def address_of(kind: Dict[str, Any], server: Dict[str, Any]) -> str:
    """The address the test reaches: `host:port`, else the `url` field."""
    values = {field: str(server.get(field) if server.get(field) not in (None, "") else spec.get("default", "")) for field, spec in (kind.get("fields") or {}).items() if isinstance(spec, dict)}
    if values.get("host"):
        return ":".join(item for item in (values["host"], values.get("port", "")) if item)
    return next((values[field] for field in ADDRESS_FIELDS if values.get(field)), "") or where_of(kind, server)


def _layers(**marks: str) -> Dict[str, str]:
    return {step: marks.get(step, SKIP) for step in STEPS}


def classify(kind: Dict[str, Any], server: Dict[str, Any], alias: str, state: str, output: str, how: str, identity: Dict[str, str], *, why: str = "", program: str = "", timeout: int = 0, blocked: str = "") -> Dict[str, Any]:
    """`{steps, broken, text, link}` of a test that did not pass. `state` is the word of `judge` (denied, down, failed) or `missing`; `how` the identity way
    (`tool`, `env`, `netonly`, `keyfile`, `token`); `identity` what the test ran with; `why` the word of `judge`; `program` the program that is not found; `timeout` the seconds a timed-out test was given.
    `blocked`: the place of the program when it is there but has no run bit. `link` names the part of the Local window that helps (`{part, focus}`), or is empty."""
    where, address = where_of(kind, server), address_of(kind, server)
    account = str(identity.get("account") or "")
    tool = str((kind.get("auth") or {}).get(server.get("auth") or next(iter(kind.get("auth") or {}), ""), {}).get("login") or "").split(" ")[0] or "the tool"
    have_credential = bool(identity) if how != "tool" else True
    lost = kind.get("signin_lost")
    if state == "missing" and program:
        return _out(_layers(program=BAD), "program", "program.blocked" if blocked else "program", {"program": program, "path": blocked}, {"part": "programs", "focus": "prog:" + program})
    if timeout:
        return _out(_layers(program=OK, signin=UNKNOWN, access=UNKNOWN, address=UNKNOWN), "", "timeout", {"seconds": timeout}, None)
    if state == "denied" and why == "other-identity":  # the program ran and answered, but not with the account the type expects: no word on any step
        return _out(_layers(program=OK, signin=UNKNOWN, access=UNKNOWN, address=UNKNOWN), "", "answer", {}, None)
    if state == "denied":
        if how != "tool" and not have_credential:
            return _out(_layers(program=OK, signin=BAD), "signin", "signin.token" if how == "token" else "signin.none", {"alias": alias}, None)
        if lost and re.search(str(lost), output or "", re.IGNORECASE | re.MULTILINE):
            return _out(_layers(program=OK, signin=BAD), "signin", "signin.tool", {"program": tool}, None)
        if how == "tool":
            if lost:  # the type told "no sign-in" apart: this answer came from the system, so the sign-in was there
                return _out(_layers(program=OK, signin=OK, access=BAD), "access", "access.tool", {"account": account or say("connections.layer.thisaccount"), "where": where}, None)
            return _out(_layers(program=OK, signin=UNKNOWN, access=UNKNOWN), "", "denied.unsure", {"account": account or say("connections.layer.thisaccount"), "where": where}, None)
        return _out(_layers(program=OK, signin=OK, access=BAD), "access", "access.token" if how == "token" else "access.typed", {"where": where, "account": account or "-"}, None)
    if state == "down" or (state == "failed" and NETWORK.search(output or "")):
        if CERT.search(output or ""):
            return _out(_layers(program=OK, signin=OK if have_credential else UNKNOWN, access=UNKNOWN, address=BAD), "address", "address.cert", {"address": address}, {"part": "network", "focus": ""})
        if PROXY.search(output or ""):
            return _out(_layers(program=OK, signin=OK if have_credential else UNKNOWN, access=UNKNOWN, address=BAD), "address", "address.proxy", {"address": address}, {"part": "network", "focus": ""})
        return _out(_layers(program=OK, signin=OK if have_credential else UNKNOWN, access=UNKNOWN, address=BAD), "address", "address", {"address": address}, None)
    first = next((line.strip() for line in (output or "").splitlines() if line.strip()), "")[:160]
    return _out(_layers(program=OK, signin=UNKNOWN, access=UNKNOWN, address=UNKNOWN), "", "error", {"first": first or say("connections.layer.nothing")}, None)


def _out(steps: Dict[str, str], broken: str, key: str, values: Dict[str, Any], link: Any) -> Dict[str, Any]:
    """The steps after the first broken one were not looked at."""
    if broken:
        seen = False
        for step in STEPS:
            if seen:
                steps[step] = SKIP
            seen = seen or step == broken
    return {"steps": steps, "broken": broken, "key": key, "text": say(f"connections.layer.{key}", local=say("tools.local.title"), **values), "link": link}


def passed() -> Dict[str, Any]:
    return {"steps": {step: OK for step in STEPS}, "broken": "", "key": "ok", "text": "", "link": None}


def names() -> List[str]:
    return list(STEPS)
