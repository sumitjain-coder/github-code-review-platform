"""
PHASE 1 PROOF OF CONCEPT
------------------------
Goal: prove that an LLM (Gemini) can actually produce a useful,
beginner-friendly code review from a diff — before we build ANY
server, webhook, or database around it.

Nothing here talks to GitHub yet. We paste in a sample diff by hand.
"""

import os
import json
from dotenv import load_dotenv
from google import genai

# ---------------------------------------------------------------
# STEP 1: Load the secret API key from the .env file
# ---------------------------------------------------------------
# load_dotenv() reads the ".env" file in this folder and makes its
# values available via os.getenv(). This keeps your key out of the
# code itself.
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError(
        "No API key found. Did you create a '.env' file (copied from "
        "'.env.example') and paste your real Gemini key into it?"
    )

# ---------------------------------------------------------------
# STEP 2: Create the Gemini client (new, currently-supported SDK)
# ---------------------------------------------------------------
# NOTE: the old "google.generativeai" package is fully retired.
# "google.genai" is the current, supported package going forward.
client = genai.Client(api_key=api_key)

# NOTE: Google periodically retires older free-tier model names.
# If you ever see a "model not found / no longer available" error,
# it means the model name below needs updating. Google's error
# message always tells you the current replacement name to use.
MODEL_NAME = "gemini-3.6-flash"

# ---------------------------------------------------------------
# STEP 3: A sample "diff" — pretend this came from a real PR
# ---------------------------------------------------------------
# In a real diff, lines starting with "+" were ADDED,
# lines starting with "-" were REMOVED,
# and the "@@ ... @@" line tells you which line numbers we're near.
# Later (Phase 2/3) this will come from GitHub automatically —
# for now we write one by hand so we control what the AI sees.
sample_diff = """
diff --git a/auth.py b/auth.py
index e69de29..b6fc4c6 100644
--- a/auth.py
+++ b/auth.py
@@ -10,7 +10,10 @@ def check_login(username, password):
     user = get_user(username)
     if user is None:
         return False
-    return user.password == password
+    # Compare passwords directly (plaintext)
+    if user.password == password:
+        return True
+    return False
"""

# ---------------------------------------------------------------
# STEP 4: The prompt — this is the most important part of the whole
# project. We tell the model exactly what to look for AND exactly
# what shape to reply in, so our Python code can read it reliably.
# ---------------------------------------------------------------
prompt = f"""
You are an experienced senior software engineer reviewing a GitHub pull request.
You are reviewing code for a BEGINNER programmer who is still learning, so your
explanations must be simple, jargon-free, and easy to understand.

Here is the diff to review:
{sample_diff}

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
"""

# ---------------------------------------------------------------
# STEP 5: Send it to Gemini and get the response back
# ---------------------------------------------------------------
response = client.models.generate_content(
    model=MODEL_NAME,
    contents=prompt,
)
raw_text = response.text.strip()

# Models sometimes wrap JSON in ```json ... ``` even when told not to.
# This cleans that up before we try to parse it.
if raw_text.startswith("```"):
    raw_text = raw_text.strip("`")
    raw_text = raw_text.replace("json", "", 1).strip()

# ---------------------------------------------------------------
# STEP 6: Parse the JSON and print it nicely
# ---------------------------------------------------------------
try:
    review = json.loads(raw_text)
except json.JSONDecodeError:
    print("The model didn't return valid JSON. Raw response was:\n")
    print(raw_text)
    raise SystemExit(1)

print("=" * 60)
print("PLAIN ENGLISH SUMMARY")
print("=" * 60)
print(review["plain_english_summary"])

print("\n" + "=" * 60)
print("IMPACT SUMMARY")
print("=" * 60)
print(review["impact_summary"])

print("\n" + "=" * 60)
print("DETAILED FINDINGS")
print("=" * 60)
for i, finding in enumerate(review["findings"], start=1):
    print(f"\n[{i}] {finding['file']} (line {finding['line']}) — {finding['severity'].upper()}")
    print(f"    Issue: {finding['issue']}")
    print(f"    Why it matters: {finding['why_it_matters']}")
    print(f"    Suggested fix: {finding['suggested_fix']}")
