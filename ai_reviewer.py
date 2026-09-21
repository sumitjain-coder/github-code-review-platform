"""
AI REVIEWER MODULE
-------------------
This is the "brain" we proved out in Phase 1, now packaged as a
reusable function instead of a standalone script. Any part of our
app (the webhook handler, later a "re-run review" button, etc.)
can call get_ai_review(diff_text) and get back structured JSON.
"""

import os
import json
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError(
        "GEMINI_API_KEY is missing from .env — the AI reviewer can't run without it."
    )

client = genai.Client(api_key=api_key)

# NOTE: Google periodically retires older free-tier model names.
# If you see a "model not found / no longer available" error,
# Google's error message will tell you the current replacement name.
MODEL_NAME = "gemini-3.6-flash"

# How many times to retry if Gemini's servers are temporarily
# overloaded (503 errors), and how long to wait between tries.
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _call_gemini_with_retry(prompt):
    """
    Calls Gemini, automatically retrying a few times if the failure
    looks temporary (like a 503 "server overloaded" error) rather
    than a real problem with our request. Returns the raw text
    response, or None if every attempt failed.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
            )
            return response.text.strip()

        except Exception as e:
            error_text = str(e)
            is_temporary_error = "503" in error_text or "UNAVAILABLE" in error_text

            if is_temporary_error and attempt < MAX_RETRIES:
                print(
                    f"Gemini is temporarily overloaded (attempt {attempt}/{MAX_RETRIES}). "
                    f"Retrying in {RETRY_DELAY_SECONDS} seconds..."
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue

            # Either it's not a temporary error, or we're out of
            # retries — give up and let the caller handle it.
            print(f"Gemini call failed permanently: {error_text}")
            return None


def get_ai_review(diff_text):
    """
    Sends a diff to Gemini and returns a parsed dict with:
      - plain_english_summary
      - impact_summary
      - findings (list of dicts: file, line, severity, issue,
        why_it_matters, suggested_fix)

    Returns None if the AI didn't return valid JSON, so callers can
    handle that gracefully instead of crashing.
    """
    prompt = f"""
You are an experienced senior software engineer reviewing a GitHub pull request.
You are reviewing code for a BEGINNER programmer who is still learning, so your
explanations must be simple, jargon-free, and easy to understand.

Here is the diff to review:
{diff_text}

Analyze this diff and respond with ONLY valid JSON (no markdown fences, no extra
text before or after) in exactly this shape:

{{
  "plain_english_summary": "1-2 sentences, in the simplest possible language, describing what this change does.",
  "impact_summary": "1-2 sentences describing what part of the app this affects and what could break if this change is wrong.",
  "findings": [
    {{
      "file": "filename",
      "line": approximate_line_number_as_integer,
      "severity": "critical | warning | suggestion",
      "issue": "what is wrong, explained simply",
      "why_it_matters": "why a beginner should care about this",
      "suggested_fix": "a short, simple suggestion on how to fix it"
    }}
  ]
}}

Rules:
- Use "critical" only for real bugs or security issues.
- Explain everything as if teaching a beginner — avoid unexplained jargon.
- If there is a security issue, you MUST mention it.
- If there are no meaningful issues, return an empty "findings" list — do not invent problems.
"""

    raw_text = _call_gemini_with_retry(prompt)
    if raw_text is None:
        return None

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json", "", 1).strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        print("AI did not return valid JSON. Raw response was:")
        print(raw_text)
        return None


def format_review_as_markdown(review):
    """
    Turns our structured review dict into a nicely formatted GitHub
    comment (GitHub renders Markdown in comments).
    """
    lines = []
    lines.append("## 🤖 AI Code Review\n")
    lines.append(f"**Summary:** {review['plain_english_summary']}\n")
    lines.append(f"**Impact:** {review['impact_summary']}\n")

    findings = review.get("findings", [])
    if not findings:
        lines.append("No significant issues found. ✅")
        return "\n".join(lines)

    lines.append("### Findings\n")
    severity_emoji = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵"}

    for finding in findings:
        emoji = severity_emoji.get(finding.get("severity", ""), "⚪")
        lines.append(
            f"{emoji} **{finding['severity'].upper()}** — "
            f"`{finding['file']}` (line {finding['line']})\n"
            f"- **Issue:** {finding['issue']}\n"
            f"- **Why it matters:** {finding['why_it_matters']}\n"
            f"- **Suggested fix:** {finding['suggested_fix']}\n"
        )

    return "\n".join(lines)
