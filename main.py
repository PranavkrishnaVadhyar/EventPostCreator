"""
Event Post Creator — Single-file pipeline
==========================================

Takes event details, stories, and extra context, then generates a
publish-ready LinkedIn post using Google Gemini.
"""

import json
import os

from dotenv import load_dotenv
import google.generativeai as genai


load_dotenv()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)



EXTRACT_PROMPT = """You are an expert event information extractor.

Given a free-form description of an event where the user was the resource person / trainer / speaker,
extract the following details and return ONLY valid JSON — no markdown, no explanation, just the JSON object.

JSON schema:
{{
  "event_name": "string or null",
  "event_type": "workshop | bootcamp | seminar | webinar | conference | other",
  "date": "string or null",
  "venue": "string or null",
  "topic": "string (main subject covered)",
  "audience": "string (who attended, e.g. 'undergraduate CS students')",
  "duration": "string or null (e.g. '2 days', '3 hours')",
  "participant_count": "string or null (e.g. '120 students')",
  "key_takeaways": ["string", "..."],
  "my_role": "string (e.g. 'Resource Person', 'Trainer', 'Speaker')",
  "organizer": "string or null (institution / org that hosted)"
}}

If a field is not mentioned, set it to null (or an empty list for arrays).

Event description:
{event_text}
"""

HOOK_PROMPT = """You are a professional content writer who specialises in crafting compelling social media hooks.

Your job is to write a powerful opening for a LinkedIn post about an event the author conducted as a resource person.

Rules:
- Write exactly 2–3 short, punchy sentences (the hook).
- Choose ONE of these styles based on what fits the stories best:
    a) Storytelling opener — start with a vivid micro-story or moment.
    b) Bold statement — a confident, thought-provoking claim.
    c) Question opener — a question that makes the reader pause.
- The hook must feel personal and authentic — written in first person.
- Do NOT include emojis. No hashtags. No "In conclusion" or filler phrases.
- Output ONLY the hook text, nothing else.

Event details (structured):
{details}

Stories / memorable moments from the event:
{stories}
"""

POST_PROMPT = """You are a professional LinkedIn ghostwriter who specialises in personal-brand content for tech educators and speakers.

Write a complete, publish-ready LinkedIn post for the author based on the information below.

Structure:
1. HOOK — use the provided hook as-is (do not rewrite it).
2. BODY — 3–5 short paragraphs covering:
   - What the event was about and who attended.
   - Key topics or modules covered (brief, not a dry list).
   - One or two specific highlights or moments of impact.
   - What the author personally found rewarding or learned.
3. CALL TO ACTION — one short sentence inviting engagement (e.g., asking a question, inviting DMs, or encouraging to follow).
4. HASHTAGS — 6–10 relevant hashtags on the last line.

Style rules:
- First person, warm yet professional tone.
- Short paragraphs (2–3 sentences max) for LinkedIn readability.
- Use line breaks between sections.
- Add relevant emojis sparingly (1–2 per section maximum).
- Do NOT use the phrases: "In conclusion", "To summarise", "I am pleased to announce".
- Do NOT hallucinate details not present in the inputs.

Inputs:

Hook:
{hook}

Structured event details:
{details}

Extra context / user instructions:
{extra_context}
"""



def extract_details(event_text: str) -> dict:
    """Send raw event description to Gemini and get structured JSON back."""
    prompt = EXTRACT_PROMPT.replace("{event_text}", event_text)
    response = model.generate_content(prompt)

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    return json.loads(raw)


def generate_hook(details: dict, stories: str) -> str:
    """Generate a 2–3 sentence hook from extracted details + stories."""
    prompt = HOOK_PROMPT.replace("{details}", json.dumps(details, indent=2))
    prompt = prompt.replace("{stories}", stories)
    response = model.generate_content(prompt)
    return response.text.strip()


def generate_post(hook: str, details: dict, extra_context: str) -> str:
    """Produce the complete LinkedIn post from hook + details + context."""
    prompt = POST_PROMPT.replace("{hook}", hook)
    prompt = prompt.replace("{details}", json.dumps(details, indent=2))
    prompt = prompt.replace("{extra_context}", extra_context or "None provided.")
    response = model.generate_content(prompt)
    return response.text.strip()


def run_pipeline(event_text: str, stories: str, extra_context: str = "") -> dict:
    """
    Orchestrate the full pipeline: extract → hook → post.

    Returns dict with keys: "details", "hook", "post".
    """
    print("🔍 Step 1/3 — Extracting event details...")
    details = extract_details(event_text)
    print("   ✅ Details extracted.\n")

    print("✨ Step 2/3 — Generating hook...")
    hook = generate_hook(details, stories)
    print(f"   ✅ Hook ready.\n")

    print("📝 Step 3/3 — Generating full post...")
    post = generate_post(hook, details, extra_context)
    print("   ✅ Post generated.\n")

    return {"details": details, "hook": hook, "post": post}


def get_multiline_input(prompt_msg: str) -> str:
    """Read multiple lines until the user presses Enter on an empty line."""
    print(prompt_msg)
    print("  (Type your text, then press Enter twice to finish)\n")
    lines = []
    while True:
        line = input()
        if line == "":
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("  🎤  Event Post Creator  —  LinkedIn Post Generator")
    print("=" * 60, "\n")

    event_text = get_multiline_input(
        "📋  Step 1/3 — Describe the event:\n"
        "  Include: event name, date, venue, topic, audience, your role, etc."
    )
    print()

    stories = get_multiline_input(
        "📖  Step 2/3 — Share stories or memorable moments from the event:\n"
        "  These will be used to craft a compelling hook."
    )
    print()

    print("🎯  Step 3/3 — Any extra context? (tone, hashtags, instructions)")
    print("  Press Enter twice to skip.\n")
    extra_lines = []
    while True:
        line = input()
        if line == "":
            break
        extra_lines.append(line)
    extra_context = "\n".join(extra_lines)
    print()

    print("-" * 60)
    result = run_pipeline(event_text, stories, extra_context)
    print("-" * 60)

    print("\n📋 EXTRACTED DETAILS:")
    print(json.dumps(result["details"], indent=2, ensure_ascii=False))

    print("\n✨ GENERATED HOOK:")
    print(result["hook"])

    print("\n" + "=" * 60)
    print("📝 YOUR LINKEDIN POST:")
    print("=" * 60)
    print(result["post"])
    print("=" * 60)

    print("\n💡 Tip: Copy the post above and paste it directly into LinkedIn!")


if __name__ == "__main__":
    main()
