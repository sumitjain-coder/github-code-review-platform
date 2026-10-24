"""
VERIFLOW — FLASK APP: WEBHOOK RECEIVER + DASHBOARD
-----------------------------------------
- /webhook             GitHub sends PR events here (protected by HMAC signature)
- /                    Dashboard: connected repositories
- /repo/<id>           Dashboard: pull requests for one repository
- /pr/<id>             Dashboard: review details for one pull request
- /api/pr/<id>/rerun   Dashboard button: re-run the AI review

The review logic itself lives in review_service.py.
"""

import os
import hmac
import hashlib
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Response, abort
from dotenv import load_dotenv
from sqlalchemy import func

from database import db
from models import Repository, PullRequest, Review, ReviewFinding
from review_service import run_review_pipeline

load_dotenv()

app = Flask(__name__)

# --- Database configuration ---
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()  # only creates tables that don't exist yet

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")

if not WEBHOOK_SECRET:
    raise ValueError(
        "GITHUB_WEBHOOK_SECRET is missing from .env — this must match "
        "the secret you typed into your GitHub App's webhook settings."
    )

if not DASHBOARD_PASSWORD:
    raise ValueError(
        "DASHBOARD_PASSWORD is missing from .env — add any password you "
        "like. It protects the dashboard, since ngrok makes it public."
    )


# ---------------------------------------------------------------
# Dashboard password protection (HTTP Basic Auth)
# ---------------------------------------------------------------
# Runs before every request. /webhook and /health are skipped:
# GitHub can't type a password, and /webhook has its own signature
# check instead. Your browser shows a login popup; username is
# "admin", password is DASHBOARD_PASSWORD from .env.
@app.before_request
def require_dashboard_login():
    if request.path in ("/webhook", "/health"):
        return None

    auth = request.authorization
    if auth and auth.username == "admin" and hmac.compare_digest(
        auth.password or "", DASHBOARD_PASSWORD
    ):
        return None

    return Response(
        "Login required.", 401,
        {"WWW-Authenticate": 'Basic realm="VeriFlow"'},
    )


# ---------------------------------------------------------------
# Webhook (unchanged behavior, much shorter now)
# ---------------------------------------------------------------
def verify_signature(payload_body, signature_header):
    if signature_header is None:
        return False

    expected_signature = "sha256=" + hmac.new(
        key=WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)


@app.route("/webhook", methods=["POST"])
def webhook():
    signature_header = request.headers.get("X-Hub-Signature-256")
    payload_body = request.get_data()

    if not verify_signature(payload_body, signature_header):
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

        if action in ("opened", "synchronize"):
            print(">> Fetching diff and generating AI review...")
            result = run_review_pipeline(
                owner=repo.get("owner", {}).get("login"),
                repo_name=repo.get("name"),
                installation_id=payload.get("installation", {}).get("id"),
                pr_number=pr.get("number"),
                pr_title=pr.get("title"),
                pr_author=pr.get("user", {}).get("login"),
                post_to_github=True,
            )
            print(f">> {result['message']}")
        else:
            print(f">> Ignoring action '{action}' for now.")
    else:
        print("Not a pull_request event — ignoring.")
        print(json.dumps(payload, indent=2)[:500])

    # Always 200: the event was received fine even if our review failed.
    return jsonify({"status": "received"}), 200


# ---------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------
SEVERITY_ORDER = {"critical": 0, "warning": 1, "suggestion": 2}


def latest_review_for(pr_id):
    return (
        Review.query.filter_by(pr_id=pr_id)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .first()
    )


def severity_counts(review):
    counts = {"critical": 0, "warning": 0, "suggestion": 0}
    if review:
        for f in review.findings:
            if f.severity in counts:
                counts[f.severity] += 1
    return counts


# ---------------------------------------------------------------
# Dashboard pages
# ---------------------------------------------------------------
PRS_PER_PAGE = 20
HISTORY_LIMIT = 50


@app.route("/", methods=["GET"])
def repos_page():
    repos = Repository.query.all()

    # Three small aggregate queries instead of looping over every PR
    # and review in Python, so this page stays fast as data grows.
    pr_counts = dict(
        db.session.query(PullRequest.repo_id, func.count(PullRequest.id))
        .group_by(PullRequest.repo_id).all()
    )
    last_review = dict(
        db.session.query(PullRequest.repo_id, func.max(Review.created_at))
        .join(Review, Review.pr_id == PullRequest.id)
        .group_by(PullRequest.repo_id).all()
    )

    # Findings only count from each PR's LATEST review
    latest_ids = (
        db.session.query(func.max(Review.id).label("rid"))
        .group_by(Review.pr_id).subquery()
    )
    totals_by_repo = {}
    severity_rows = (
        db.session.query(PullRequest.repo_id, ReviewFinding.severity, func.count(ReviewFinding.id))
        .select_from(PullRequest)
        .join(Review, Review.pr_id == PullRequest.id)
        .join(latest_ids, latest_ids.c.rid == Review.id)
        .join(ReviewFinding, ReviewFinding.review_id == Review.id)
        .group_by(PullRequest.repo_id, ReviewFinding.severity).all()
    )
    for repo_id, severity, count in severity_rows:
        totals_by_repo.setdefault(repo_id, {})[severity] = count

    # Most recently active repositories first (name order breaks ties)
    repos.sort(key=lambda r: (r.owner.lower(), r.name.lower()))
    repos.sort(key=lambda r: last_review.get(r.id) or datetime.min, reverse=True)

    repo_cards = []
    for repo in repos:
        sev = totals_by_repo.get(repo.id, {})
        repo_cards.append({
            "repo": repo,
            "pr_count": pr_counts.get(repo.id, 0),
            "last_review": last_review.get(repo.id),
            "totals": {k: sev.get(k, 0) for k in ("critical", "warning", "suggestion")},
        })

    return render_template("repos.html", repo_cards=repo_cards)


@app.route("/repo/<int:repo_id>", methods=["GET"])
def repo_page(repo_id):
    repo = db.session.get(Repository, repo_id)
    if repo is None:
        abort(404)

    page = request.args.get("page", 1, type=int)
    pagination = (
        PullRequest.query.filter_by(repo_id=repo.id)
        .order_by(PullRequest.pr_number.desc())
        .paginate(page=page, per_page=PRS_PER_PAGE, error_out=False)
    )

    rows = []
    for pr in pagination.items:
        review = latest_review_for(pr.id)
        rows.append({"pr": pr, "review": review, "counts": severity_counts(review)})

    return render_template("repo_detail.html", repo=repo, rows=rows, pagination=pagination)


@app.route("/pr/<int:pr_id>", methods=["GET"])
def review_page(pr_id):
    pr = db.session.get(PullRequest, pr_id)
    if pr is None:
        abort(404)

    history = (
        Review.query.filter_by(pr_id=pr.id)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    total_reviews = Review.query.filter_by(pr_id=pr.id).count()

    # Show a specific past review if ?review=<id> is given, else the latest
    selected = None
    requested_id = request.args.get("review", type=int)
    if requested_id:
        selected = Review.query.filter_by(id=requested_id, pr_id=pr.id).first()
    if selected is None and history:
        selected = history[0]

    finding_counts = {}
    if history:
        finding_counts = dict(
            db.session.query(ReviewFinding.review_id, func.count(ReviewFinding.id))
            .filter(ReviewFinding.review_id.in_([r.id for r in history]))
            .group_by(ReviewFinding.review_id).all()
        )

    findings = []
    if selected:
        findings = sorted(
            selected.findings,
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.file_path or "", f.line_number or 0),
        )

    return render_template(
        "review_detail.html",
        pr=pr,
        repo=pr.repository,
        review=selected,
        findings=findings,
        counts=severity_counts(selected),
        history=history,
        total_reviews=total_reviews,
        finding_counts=finding_counts,
    )


# ---------------------------------------------------------------
# API used by the dashboard's "Re-run Review" button (via fetch)
# ---------------------------------------------------------------
@app.route("/api/pr/<int:pr_id>/rerun", methods=["POST"])
def rerun_review(pr_id):
    pr = db.session.get(PullRequest, pr_id)
    if pr is None:
        return jsonify({"ok": False, "message": "Pull request not found."}), 404

    repo = pr.repository
    result = run_review_pipeline(
        owner=repo.owner,
        repo_name=repo.name,
        installation_id=repo.installation_id,
        pr_number=pr.pr_number,
        pr_title=pr.title,
        pr_author=pr.author,
        post_to_github=False,  # dashboard re-runs don't spam the PR
    )
    return jsonify(result), (200 if result["ok"] else 502)


@app.route("/health", methods=["GET"])
def health_check():
    return "Webhook server is running."


if __name__ == "__main__":
    app.run(port=5000, debug=True)
