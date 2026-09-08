"""
GITHUB CLIENT MODULE
---------------------
Everything related to talking to GitHub's API lives here, separate
from our Flask routes and separate from our AI logic. This keeps
each file focused on one job — a good habit for any real project.

Concepts used here (see Phase 3 study notes):
1. We sign a short-lived JWT using our App's private key (.pem file)
   to prove "we are legitimately this GitHub App."
2. We exchange that JWT for an "installation access token" — a
   temporary token scoped to the specific repo(s) our app is
   installed on. This is what we actually use for real API calls.
"""

import os
import time
import jwt  # from the PyJWT package
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")

GITHUB_API_BASE = "https://api.github.com"


def _load_private_key():
    with open(PRIVATE_KEY_PATH, "r") as key_file:
        return key_file.read()


def generate_app_jwt():
    """
    Creates a short-lived (10 minute) signed token proving we are
    legitimately this GitHub App. This is NOT used for normal API
    calls — it's only used once, to request an installation token.
    """
    private_key = _load_private_key()
    now = int(time.time())

    payload = {
        "iat": now - 60,       # issued-at, backdated slightly to avoid clock drift issues
        "exp": now + (10 * 60),  # expires in 10 minutes (GitHub's max allowed)
        "iss": GITHUB_APP_ID,  # who is issuing this token (our App ID)
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(installation_id):
    """
    Exchanges our App-level JWT for a temporary token scoped to one
    specific installation (i.e., one specific set of repos). This is
    the token we'll actually use to fetch diffs and post comments.
    """
    app_jwt = generate_app_jwt()

    url = f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
    }

    response = requests.post(url, headers=headers)
    response.raise_for_status()  # raises an error if something went wrong

    return response.json()["token"]


def get_pr_diff(owner, repo, pr_number, installation_token):
    """
    Fetches the list of changed files in a PR, and combines their
    individual patches into one diff-like text block we can hand
    to the AI.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {installation_token}",
        "Accept": "application/vnd.github+json",
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    files = response.json()

    combined_diff_parts = []
    for file in files:
        filename = file.get("filename")
        patch = file.get("patch")  # some files (e.g. binary, renamed-only) have no patch
        if patch:
            combined_diff_parts.append(f"--- {filename} ---\n{patch}")

    return "\n\n".join(combined_diff_parts)


def post_pr_comment(owner, repo, pr_number, installation_token, body):
    """
    Posts a single comment on the PR. Note: PR comments use the
    "issues" endpoint in GitHub's API — every PR is internally also
    an "issue," which is a common source of confusion.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {installation_token}",
        "Accept": "application/vnd.github+json",
    }

    response = requests.post(url, headers=headers, json={"body": body})
    response.raise_for_status()

    return response.json()
