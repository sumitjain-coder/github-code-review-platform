"""
DATABASE MODELS
----------------
Each class below becomes one MySQL table. SQLAlchemy reads these
Python classes and generates the actual "CREATE TABLE" SQL for us —
we never write raw SQL by hand.

Schema shape (see Phase 4 study notes):
  Repository  --(has many)-->  PullRequest
  PullRequest --(has many)-->  Review
  Review      --(has many)-->  ReviewFinding
"""

from datetime import datetime
from database import db


class Repository(db.Model):
    __tablename__ = "repositories"

    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    installation_id = db.Column(db.String(255), nullable=False)

    # "relationship" doesn't create a column — it just gives us a
    # convenient way to write repo.pull_requests in Python and get
    # back all related rows, without writing a JOIN ourselves.
    pull_requests = db.relationship("PullRequest", backref="repository", lazy=True)


class PullRequest(db.Model):
    __tablename__ = "pull_requests"

    id = db.Column(db.Integer, primary_key=True)
    repo_id = db.Column(db.Integer, db.ForeignKey("repositories.id"), nullable=False)
    pr_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default="reviewed")  # reviewed / pending / failed

    reviews = db.relationship("Review", backref="pull_request", lazy=True)


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    pr_id = db.Column(db.Integer, db.ForeignKey("pull_requests.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    plain_english_summary = db.Column(db.Text)
    impact_summary = db.Column(db.Text)
    raw_llm_response = db.Column(db.Text)  # full JSON, kept for debugging/audit

    findings = db.relationship("ReviewFinding", backref="review", lazy=True)


class ReviewFinding(db.Model):
    __tablename__ = "review_findings"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id"), nullable=False)
    file_path = db.Column(db.String(500))
    line_number = db.Column(db.Integer)
    severity = db.Column(db.String(50))  # critical / warning / suggestion
    issue = db.Column(db.Text)
    why_it_matters = db.Column(db.Text)
    suggested_fix = db.Column(db.Text)
