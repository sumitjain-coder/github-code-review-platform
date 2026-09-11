"""
PERSISTENCE MODULE
-------------------
Handles writing a completed review into the database. Kept separate
from app.py so the webhook handler doesn't need to know HOW data
gets saved, just that it does.
"""

from database import db
from models import Repository, PullRequest, Review, ReviewFinding


def get_or_create_repository(owner, name, installation_id):
    repo = Repository.query.filter_by(owner=owner, name=name).first()
    if repo is None:
        repo = Repository(owner=owner, name=name, installation_id=str(installation_id))
        db.session.add(repo)
        db.session.commit()  # commit now so repo.id exists for use below
    return repo


def save_review(owner, repo_name, installation_id, pr_number, pr_title, pr_author, review_data):
    """
    Saves a full review (and all its findings) to the database.
    review_data is the dict returned by get_ai_review() in ai_reviewer.py.
    """
    repo = get_or_create_repository(owner, repo_name, installation_id)

    pull_request = PullRequest.query.filter_by(repo_id=repo.id, pr_number=pr_number).first()
    if pull_request is None:
        pull_request = PullRequest(
            repo_id=repo.id,
            pr_number=pr_number,
            title=pr_title,
            author=pr_author,
            status="reviewed",
        )
        db.session.add(pull_request)
        db.session.commit()
    else:
        # PR was updated (new commits) — refresh the title in case it changed
        pull_request.title = pr_title
        pull_request.status = "reviewed"
        db.session.commit()

    review = Review(
        pr_id=pull_request.id,
        plain_english_summary=review_data.get("plain_english_summary"),
        impact_summary=review_data.get("impact_summary"),
        raw_llm_response=str(review_data),
    )
    db.session.add(review)
    db.session.commit()  # commit now so review.id exists for findings below

    for finding in review_data.get("findings", []):
        db.session.add(
            ReviewFinding(
                review_id=review.id,
                file_path=finding.get("file"),
                line_number=finding.get("line"),
                severity=finding.get("severity"),
                issue=finding.get("issue"),
                why_it_matters=finding.get("why_it_matters"),
                suggested_fix=finding.get("suggested_fix"),
            )
        )

    db.session.commit()
    return review
