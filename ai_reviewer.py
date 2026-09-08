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

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    raw_text = response.text.strip()

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
