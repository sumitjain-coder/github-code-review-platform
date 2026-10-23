"""
REVIEW SERVICE
---------------
The full review pipeline (fetch diff -> AI review -> post to GitHub
-> save to MySQL) as ONE reusable function.

Before Phase 6 this logic lived inside the webhook handler. Now both
the webhook (automatic reviews) and the dashboard's "Re-run Review"
button (manual reviews) call the same function, so there is only one
place to fix or improve it.
"""

from github_client import (
    get_installation_token,
    fetch_pr_files,
    build_diff_text,
    post_pr_review,
    post_pr_comment,
)
from ai_reviewer import get_ai_review
from diff_utils import build_line_to_position_map
from persistence import save_review

SEVERITY_EMOJI = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵"}


def _build_inline_comments(review, files):
    """
    Translates the AI's findings into GitHub inline comments.
    Returns (inline_comments, unmapped_findings). A finding is
    "unmapped" if its line number isn't part of the diff, in which
    case it goes into the summary text instead of being lost.
    """
    position_maps_by_file = {}
    for file in files:
        if file.get("patch"):
            position_maps_by_file[file["filename"]] = build_line_to_position_map(file["patch"])

    inline_comments = []
    unmapped_findings = []

    for finding in review.get("findings", []):
        file_path = finding.get("file")
        position = position_maps_by_file.get(file_path, {}).get(finding.get("line"))

        comment_text = (
            f"{SEVERITY_EMOJI.get(finding.get('severity'), '⚪')} "
            f"**{(finding.get('severity') or '').upper()}**\n\n"
            f"**Issue:** {finding.get('issue')}\n\n"
            f"**Why it matters:** {finding.get('why_it_matters')}\n\n"
            f"**Suggested fix:** {finding.get('suggested_fix')}"
        )

        if position is not None:
            inline_comments.append({"path": file_path, "position": position, "body": comment_text})
        else:
            unmapped_findings.append(finding)

    return inline_comments, unmapped_findings


def _build_summary_body(review, unmapped_findings):
    body = (
        "## 🤖 AI Code Review\n\n"
        f"**Summary:** {review.get('plain_english_summary')}\n\n"
        f"**Impact:** {review.get('impact_summary')}\n"
    )

    if not review.get("findings"):
        body += "\nNo significant issues found. ✅"

    if unmapped_findings:
        body += "\n\n### Additional notes (couldn't attach to an exact line)\n"
        for f in unmapped_findings:
            body += f"- **{f.get('file')}**: {f.get('issue')}\n"

    return body


def run_review_pipeline(owner, repo_name, installation_id, pr_number,
                        pr_title, pr_author, post_to_github=True):
    """
    Runs one full review. Returns a dict the caller can show or log:
        {"ok": True/False, "message": "...", "review_id": int or None}

    post_to_github=False runs the review and saves it to the database
    WITHOUT posting anything on the PR. The dashboard's "Re-run Review"
    button uses this so repeated clicks don't spam the pull request.
    """
    try:
        installation_token = get_installation_token(installation_id)

        files = fetch_pr_files(owner, repo_name, pr_number, installation_token)
        diff_text = build_diff_text(files)

        if not diff_text:
            return {"ok": False, "review_id": None,
                    "message": "No reviewable text changes found (e.g. binary files only)."}

        review = get_ai_review(diff_text)
        if review is None:
            return {"ok": False, "review_id": None,
                    "message": "The AI did not return a usable review. Try again in a moment."}

        if post_to_github:
            inline_comments, unmapped = _build_inline_comments(review, files)
            summary_body = _build_summary_body(review, unmapped)

            if inline_comments:
                post_pr_review(owner, repo_name, pr_number, installation_token,
                               summary_body, inline_comments)
                print(f">> Review posted with {len(inline_comments)} inline comment(s).")
            else:
                post_pr_comment(owner, repo_name, pr_number, installation_token, summary_body)
                print(">> Summary comment posted (no inline comments this time).")

        saved = save_review(
            owner=owner,
            repo_name=repo_name,
            installation_id=installation_id,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_author=pr_author,
            review_data=review,
        )
        print(">> Review saved to database.")

        return {"ok": True, "review_id": saved.id, "message": "Review completed."}

    except Exception as e:
        print(f">> Something went wrong during the review process: {e}")
        return {"ok": False, "review_id": None, "message": f"Review failed: {e}"}
