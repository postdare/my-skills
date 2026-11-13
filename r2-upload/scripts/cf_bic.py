#!/usr/bin/env python3
"""Manage the Cloudflare Browser Integrity Check (BIC) rule for an R2 custom domain.

Why this exists
---------------
Cloudflare's Browser Integrity Check rejects requests whose User-Agent looks
like a script. Python's urllib sends "Python-urllib/x.y" by default, and BIC
answers those with:

    HTTP 403 Forbidden
    error code: 1010

The upload itself is unaffected (it goes to *.r2.cloudflarestorage.com, which
does not run BIC). What breaks is *reading* the object back through the custom
domain, so browser and curl both return 200 while a Python client returns 403.
That is easy to misread as "the object is missing".

Two ways to fix it, in order of preference:

  1. skip  -- a zone-level skip rule scoped to the storage hostname, skipping
              the `bic` product. Precise: the rest of the zone keeps BIC.
              Requires the "Skip security products" option, which is an
              Enterprise-only feature.

  2. zone  -- turn the zone-wide `browser_check` setting off. Works on every
              plan, but disables BIC for the entire zone, including the main
              site and any other hostname under it.

The script is idempotent: it reads the current state first and only changes
what is needed.

Usage
-----
    export CLOUDFLARE_API_TOKEN=<your token>
    python3 cf_bic.py --domain public-oss.haren.app --plan skip
    python3 cf_bic.py --domain public-oss.haren.app --plan zone
    python3 cf_bic.py --domain public-oss.haren.app --status

The token needs:
  Zone -> Zone -> Read          (to find the zone id)
  Zone -> Zone Settings -> Edit  (for the zone-wide switch)
  Zone -> Zone WAF -> Edit      (for skip rules, Enterprise only)

Note: an R2 API token cannot call this API. R2 tokens only authenticate
against the storage endpoint. Use a separate token from
Cloudflare Dashboard -> My Profile -> API Tokens.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("CF_API_BASE", "https://api.cloudflare.com/client/v4").rstrip("/")

# The rule description is used to find a rule this script created earlier.
RULE_DESC = "r2-upload: skip Browser Integrity Check for the R2 custom domain"
RULE_NAME = "skip-bic-r2-custom-domain"


class CFError(RuntimeError):
    pass


def api(method, path, token, body=None):
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "r2-upload/cf-bic/1.0")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
            msgs = "; ".join(
                "%s: %s" % (e.get("code"), e.get("message")) for e in payload.get("errors", [])
            )
        except Exception:
            msgs = raw[:300]
        raise CFError("HTTP %s %s -> %s" % (e.code, e.reason, msgs))
    except urllib.error.URLError as e:
        raise CFError("network error: %s" % e.reason)


def require_success(payload, what):
    if not payload.get("success"):
        raise CFError("%s failed: %s" % (what, json.dumps(payload.get("errors"), ensure_ascii=False)))
    return payload.get("result")


def find_zone(token, domain):
    """Return (zone_id, zone_name) for the zone containing `domain`."""
    # Cloudflare wants the root name; try progressively shorter labels.
    labels = domain.split(".")
    candidates = [".".join(labels[i:]) for i in range(0, len(labels) - 1)]
    for name in candidates:
        res = require_success(
            api("GET", "/zones?name=%s" % name, token), "list zones"
        )
        if res:
            z = res[0]
            return z["id"], z["name"]
    raise CFError("no Cloudflare zone found for %s" % domain)


def get_setting(token, zone_id, setting_id):
    res = require_success(
        api("GET", "/zones/%s/settings/%s" % (zone_id, setting_id), token), "get setting"
    )
    return res.get("value"), res.get("editable")


def set_setting(token, zone_id, setting_id, value):
    res = require_success(
        api("PATCH", "/zones/%s/settings/%s" % (zone_id, setting_id), token, {"value": value}),
        "update setting",
    )
    return res.get("value")


def get_custom_ruleset(token, zone_id):
    """Return the zone-level http_request_firewall_custom entry point ruleset."""
    path = "/zones/%s/rulesets/phases/http_request_firewall_custom/entrypoint" % zone_id
    try:
        res = require_success(api("GET", path, token), "get custom ruleset")
    except CFError as e:
        if "404" in str(e) or "no ruleset" in str(e).lower():
            return None
        raise
    return res


def find_our_rule(ruleset):
    if not ruleset:
        return None
    for r in ruleset.get("rules", []):
        if r.get("description") == RULE_DESC:
            return r
    return None


def create_skip_rule(token, zone_id, ruleset, hostname):
    """Create the skip rule, either into the existing ruleset or a new entry point."""
    rule = {
        "action": "skip",
        "action_parameters": {"products": ["bic"]},
        "expression": 'http.host eq "%s"' % hostname,
        "description": RULE_DESC,
        "enabled": True,
        "logging": {"enabled": True},
    }

    if ruleset:
        path = "/zones/%s/rulesets/%s/rules" % (zone_id, ruleset["id"])
        try:
            require_success(api("POST", path, token, rule), "create skip rule")
            return "created rule in existing ruleset %s" % ruleset["id"]
        except CFError as e:
            msg = str(e)
            if "20120" in msg or "not authorized" in msg:
                raise CFError(
                    "skip products is not available on this plan: %s\n"
                    "Use --plan zone instead (turns Browser Integrity Check off for "
                    "the whole zone, not just this hostname)." % msg
                )
            raise

    # No entry point ruleset yet: create one with the rule in it.
    body = {
        "name": "default",
        "kind": "zone",
        "phase": "http_request_firewall_custom",
        "rules": [rule],
    }
    try:
        res = require_success(
            api("POST", "/zones/%s/rulesets" % zone_id, token, body), "create ruleset"
        )
        return "created ruleset %s with skip rule" % res.get("id")
    except CFError as e:
        msg = str(e)
        if "20120" in msg or "not authorized" in msg:
            raise CFError(
                "skip products is not available on this plan: %s\n"
                "Use --plan zone instead (turns Browser Integrity Check off for "
                "the whole zone, not just this hostname)." % msg
            )
        raise


def delete_our_rule(token, zone_id, ruleset, rule):
    path = "/zones/%s/rulesets/%s/rules/%s" % (zone_id, ruleset["id"], rule["id"])
    require_success(api("DELETE", path, token), "delete rule")
    return "deleted rule %s" % rule["id"]


def show_status(token, zone_id, hostname):
    value, editable = get_setting(token, zone_id, "browser_check")
    print("zone browser_check setting : %s (editable=%s)" % (value, editable))
    rs = get_custom_ruleset(token, zone_id)
    if rs:
        print("custom ruleset id           : %s" % rs.get("id"))
        our = find_our_rule(rs)
        if our:
            print("our skip rule              : id=%s action=%s enabled=%s"
                  % (our.get("id"), our.get("action"), our.get("enabled")))
            print("  expression                : %s" % our.get("expression"))
        else:
            print("our skip rule              : (not present)")
        print("other rules in ruleset      : %d" % len(rs.get("rules", [])))
    else:
        print("custom ruleset              : (none)")
    return value


def main():
    ap = argparse.ArgumentParser(
        description="Manage Cloudflare Browser Integrity Check for an R2 custom domain."
    )
    ap.add_argument("--domain", required=True, help="the R2 custom domain, e.g. public-oss.haren.app")
    ap.add_argument("--plan", choices=["skip", "zone"], default="skip",
                    help="skip = hostname-scoped skip rule (Enterprise); "
                         "zone = turn zone-wide browser_check off (all plans)")
    ap.add_argument("--status", action="store_true", help="print the current state and exit")
    ap.add_argument("--remove", action="store_true", help="remove the skip rule this script created")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        print("ERROR: CLOUDFLARE_API_TOKEN is not set.\n"
              "Create one at Cloudflare Dashboard -> My Profile -> API Tokens.\n"
              "An R2 API token does NOT work here; R2 tokens only authenticate "
              "against the storage endpoint.", file=sys.stderr)
        return 2

    try:
        zone_id, zone_name = find_zone(token, args.domain)
    except CFError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1

    print("domain     : %s" % args.domain)
    print("zone       : %s (%s)" % (zone_name, zone_id))
    print()

    try:
        if args.status:
            show_status(token, zone_id, args.domain)
            return 0

        rs = get_custom_ruleset(token, zone_id)
        our = find_our_rule(rs)

        if args.remove:
            if not our:
                print("nothing to remove")
                return 0
            if not args.yes:
                print("About to %s" % delete_our_rule.__name__)
                if input("confirm? [y/N] ").strip().lower() != "y":
                    print("aborted")
                    return 1
            print(delete_our_rule(token, zone_id, rs, our))
            return 0

        if args.plan == "zone":
            cur, editable = get_setting(token, zone_id, "browser_check")
            if cur == "off":
                print("browser_check is already off. nothing to do.")
                return 0
            if not args.yes:
                print("This turns Browser Integrity Check OFF for the whole zone %s," % zone_name)
                print("which affects every hostname under it, not just %s." % args.domain)
                if input("continue? [y/N] ").strip().lower() != "y":
                    print("aborted")
                    return 1
            new = set_setting(token, zone_id, "browser_check", "off")
            print("browser_check: %s -> %s" % (cur, new))
            return 0

        # plan == skip
        if our:
            print("skip rule already present (id=%s)" % our.get("id"))
            print("expression : %s" % our.get("expression"))
            return 0

        if not args.yes:
            print("This adds a zone-level skip rule:")
            print("  action       : skip")
            print("  products     : bic  (Browser Integrity Check)")
            print("  expression   : http.host eq \"%s\"" % args.domain)
            print("Every other hostname under %s keeps Browser Integrity Check." % zone_name)
            print()
            if input("continue? [y/N] ").strip().lower() != "y":
                print("aborted")
                return 1

        print(create_skip_rule(token, zone_id, rs, args.domain))
        print()
        show_status(token, zone_id, args.domain)
        return 0

    except CFError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
