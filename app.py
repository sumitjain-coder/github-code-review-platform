"""
PHASE 3: FULL PIPELINE — WEBHOOK -> DIFF -> AI -> COMMENT
-----------------------------------------------------------
Goal: when a PR is opened or updated, automatically fetch the real
diff, send it to Gemini for review, and post the AI's review back
as a comment on the PR itself — a full end-to-end loop.
"""

import os
import hmac
import hashlib
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from github_client import get_installation_token, get_pr_diff, post_pr_comment
from ai_reviewer import get_ai_review, format_review_as_markdown
from database import db
from persistence import save_review

load_dotenv()

app = Flask(__name__)

# --- Database configuration ---
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False  # extra overhead we don't need

db.init_app(app)

with app.app_context():
    # Creates any tables that don't exist yet, based on models.py.
    # Safe to run every time — it won't touch tables that already exist.
    import models  # noqa: F401 (must be imported so SQLAlchemy knows about the models)
    db.create_all()

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
            print(">> Fetching diff and generating AI review...")

            installation_id = payload.get("installation", {}).get("id")
            owner = repo.get("owner", {}).get("login")
            repo_name = repo.get("name")
            pr_number = pr.get("number")

            try:
                # Step 1: Get a temporary token scoped to this installation
                installation_token = get_installation_token(installation_id)

                # Step 2: Fetch the actual code changes
                diff_text = get_pr_diff(owner, repo_name, pr_number, installation_token)

                if not diff_text:
                    print(">> No reviewable text changes found in this PR (e.g. binary files only).")
                else:
                    # Step 3: Send the diff to Gemini for review
                    review = get_ai_review(diff_text)

                    if review is None:
                        print(">> AI review failed (invalid JSON returned). Skipping comment.")
                    else:
                        # Step 4: Post the review back on the PR
                        comment_body = format_review_as_markdown(review)
                        post_pr_comment(owner, repo_name, pr_number, installation_token, comment_body)
                        print(">> Review posted successfully on the PR.")

                        # Step 5: Save everything to MySQL for history/dashboard later
                        save_review(
                            owner=owner,
                            repo_name=repo_name,
                            installation_id=installation_id,
                            pr_number=pr_number,
                            pr_title=pr.get("title"),
                            pr_author=pr.get("user", {}).get("login"),
                            review_data=review,
                        )
                        print(">> Review saved to database.")

            except Exception as e:
                # We deliberately don't let a failed review crash the whole
                # webhook handler — we log it and move on. GitHub still gets
                # a 200 response either way (see below), since the event
                # itself was received fine even if our review step failed.
                print(f">> Something went wrong during the review process: {e}")
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
