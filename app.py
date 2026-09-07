"""
PHASE 2: FLASK WEBHOOK RECEIVER
--------------------------------
Goal: prove GitHub can actually reach our server and send us real
pull_request event data. We do NOT call the AI yet, and we do NOT
post anything back to GitHub yet — this phase is only about
receiving and verifying events safely.
"""

import os
import hmac
import hashlib
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")

if not WEBHOOK_SECRET:
    raise ValueError(
        "GITHUB_WEBHOOK_SECRET is missing from .env — this must match "
        "the secret you typed into your GitHub App's webhook settings."
    )


def verify_signature(payload_body, signature_header):
    """
    GitHub signs every webhook request using our shared secret.
    This function recalculates that signature ourselves and compares
    it to the one GitHub sent. If they don't match, either the secret
    is wrong, or the request didn't really come from GitHub at all.
    """
    if signature_header is None:
        return False

    # GitHub sends the signature as "sha256=<hexdigest>"
    expected_signature = "sha256=" + hmac.new(
        key=WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # hmac.compare_digest prevents "timing attacks" — a security best
    # practice for comparing secret values instead of using "==".
    return hmac.compare_digest(expected_signature, signature_header)


@app.route("/webhook", methods=["POST"])
def webhook():
    signature_header = request.headers.get("X-Hub-Signature-256")
    payload_body = request.get_data()  # raw bytes, needed for signature check

    if not verify_signature(payload_body, signature_header):
        # Someone (or something) sent us a request that isn't really
        # from GitHub. Reject it.
        return jsonify({"error": "Invalid signature"}), 401

    event_type = request.headers.get("X-GitHub-Event")
    payload = request.get_json()

    print(f"\n{'=' * 60}")
    print(f"Received GitHub event: {event_type}")
    print(f"{'=' * 60}")

    if event_type == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})

        print(f"Action: {action}")
        print(f"Repo: {repo.get('full_name')}")
        print(f"PR #{pr.get('number')}: {pr.get('title')}")
        print(f"Author: {pr.get('user', {}).get('login')}")

        # We only care about these two actions for now:
        # "opened"     -> a brand new PR was created
        # "synchronize" -> new commits were pushed to an existing PR
        if action in ("opened", "synchronize"):
            print(">> This is a PR we should review (later phases will do this).")
        else:
            print(f">> Ignoring action '{action}' for now.")
    else:
        print("Not a pull_request event — ignoring.")
        print(json.dumps(payload, indent=2)[:500])  # just a peek, not the whole thing

    # GitHub expects a 2xx response quickly, or it will consider the
    # delivery failed and may retry.
    return jsonify({"status": "received"}), 200


@app.route("/", methods=["GET"])
def health_check():
    # Just a simple page so you can confirm the server is alive
    # by visiting the URL in a browser.
    return "Webhook server is running."


if __name__ == "__main__":
    app.run(port=5000, debug=True)
