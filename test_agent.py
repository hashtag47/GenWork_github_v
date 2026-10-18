import os
import re
import ast
import sys
import glob
import difflib
import subprocess
from datetime import date
from agent_utils import (client, call_cost, strip_fences, load_latest_backlog,
                         approval_status, is_approved, find_directives, team_tests, APPROVED_LINE)

# A different model from the developer agent (Sonnet): two models are less likely
# to share the same misunderstanding of a story.
MODEL = "openai/gpt-5.6-luna"

RULES = """Rules:
- Test behaviour through the HTTP API only, using the `client` fixture from conftest.py.
  Never import from app/ and never touch the database directly.
- Cover EVERY acceptance criterion. Put a comment `# AC: <the criterion>` above the
  test(s) for it.
- Add the edge cases a careful tester would check (empty or missing fields, duplicates,
  not-found ids), each with a comment `# EDGE: <why>`.
- Wherever the story does not say something your test must decide (a URL, a status code,
  a field name, an error format), choose sensibly, stay consistent with the existing
  tests, and mark it with `# DECISION: <what you decided>`. Humans will review these.
- Each test must be independent: every test starts with an empty database.
- Output ONLY the Python test code. No header comments, no markdown fences, no explanations."""

DRAFT_PROMPT = """You are a test engineer writing pytest tests for a Flask JSON API, BEFORE the
feature exists. You write tests from the user story and its acceptance criteria only.
You have not seen, and must not guess at, any implementation.

{rules}

CONFTEST.PY:
{conftest}

EXISTING APPROVED TESTS (follow their URL and JSON conventions):
{existing}

USER STORY {story_id}: {story}

ACCEPTANCE CRITERIA:
{criteria}"""

REVISE_PROMPT = """You are a test engineer revising a pytest file that a human team has reviewed.
They have left instructions in comments starting with `# @TEST-AGENT:`.

Carry out every `# @TEST-AGENT:` instruction, then delete those instruction comments.
Change NOTHING else: keep every other test, comment and line exactly as it is.
Tests marked `# ADDED BY TEAM` belong to the humans: copy them through character for character.
If an instruction changes a decision, update every test it affects and its `# DECISION:` comment.

{rules}

CONFTEST.PY:
{conftest}

USER STORY {story_id}: {story}

ACCEPTANCE CRITERIA:
{criteria}

THE FILE TO REVISE:
{current}"""

def existing_tests(skip):
    parts = []
    for path in sorted(glob.glob("tests/test_*.py")):
        if path != skip:
            with open(path) as f:
                source = f.read()
            if is_approved(source) or path.endswith("test_health.py"):
                parts.append(f"# {path}\n{source}")
    return "\n\n".join(parts) or "(none yet)"

def strip_header(source):
    """Remove the header that Python writes (everything up to and including APPROVED-BY)."""
    match = APPROVED_LINE.search(source)
    return source[match.end():].lstrip("\n") if match else source

def check(code, required_team_tests):
    """Raise ValueError if the agent's code is unusable or touched the team's tests."""
    tree = ast.parse(code)
    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in tree.body):
        raise ValueError("no test_ functions found")
    if find_directives(code):
        raise ValueError("some # @TEST-AGENT: instructions were left in the file")
    now = team_tests(code)
    for name, text in required_team_tests.items():
        if now.get(name) != text:
            raise ValueError(f"the team's test {name} was changed or removed; copy it through exactly")

def ask_agent(prompt, required_team_tests, retries=1):
    messages, total = [{"role": "user", "content": prompt}], 0.0
    for attempt in range(retries + 1):
        response = client.chat.completions.create(model=MODEL, messages=messages,
                                                  max_completion_tokens=4000, temperature=0.2)
        total += call_cost(MODEL, response)
        code = strip_fences(response.choices[0].message.content)
        try:
            check(code, required_team_tests)
            return code, total
        except (SyntaxError, ValueError) as e:
            print(f"  Attempt {attempt + 1} rejected: {e}. Asking again...")
            messages += [{"role": "assistant", "content": code},
                         {"role": "user", "content": f"Rejected: {e}. Return ONLY the corrected Python test code."}]
    sys.exit("Error: the test agent did not produce an acceptable file. Nothing was saved.")

def header(story_id, story, action):
    one_line = " ".join(str(story.get("story", "")).split())
    return (f"# Story {story_id}: {one_line}\n"
            f"# {action} by test_agent.py ({MODEL}) on {date.today().isoformat()}.\n"
            f"# Review with the checklist in Activity 5, then sign off with: python sign_tests.py\n"
            f"# APPROVED-BY:\n\n")

def report(code, criteria, test_file):
    tests = re.findall(r"^def (test_\w+)", code, re.MULTILINE)
    print(f"\n{test_file}: {len(tests)} tests, {len(team_tests(code))} of them added by your team\n")
    print("ACCEPTANCE CRITERIA IN THE STORY:")
    for line in criteria.splitlines():
        print(f"  {line.strip()}")
    print("\nCRITERIA THE TESTS SAY THEY COVER:")
    for c in re.findall(r"#\s*AC:\s*(.+)", code):
        print(f"  AC: {c}")
    print("\nDECISIONS IN THESE TESTS (review every one):")
    for d in re.findall(r"#\s*DECISION:\s*(.+)", code) or ["(none marked: check the URLs and status codes yourself)"]:
        print(f"  DECISION: {d}")
    print("  If a decision is a product rule (not just a URL or status code), also record it in")
    print("  the backlog's acceptance criteria with iterate_backlog.py.")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test_file],
                            capture_output=True, text=True)
    print("\nWARNING: these tests already pass, so they may not test anything new." if result.returncode == 0
          else "\nThe tests fail for now (red). The developer agent's job is to make them pass.")

if __name__ == "__main__":
    path, version, backlog = load_latest_backlog()
    stories = {s["id"]: s for s in backlog["user_stories"]}
    committed = backlog.get("sprint_1", {}).get("committed", [])
    default = committed[0] if committed else ""
    story_id = input(f"Story id [{default}]: ").strip() or default
    if story_id not in stories:
        sys.exit(f"Error: no story '{story_id}' in {path}")
    story = stories[story_id]
    if story.get("open_questions"):
        sys.exit(f"{story_id} still has open questions. Answer them first (Definition of Ready).")

    test_file = f"tests/test_{story_id}.py"
    with open("tests/conftest.py") as f:
        conftest = f.read()
    criteria = str(story.get("acceptance_criteria", "")).strip()
    current = open(test_file).read() if os.path.exists(test_file) else None
    directives = find_directives(current) if current else []

    if directives:
        # ---- REVISE: carry out the team's @TEST-AGENT instructions, change nothing else ----
        print(f"Revising {test_file}. Instructions from your team:")
        for d in directives:
            print(f"  @TEST-AGENT: {d}")
        if approval_status(current) != "unsigned":
            print("  (This file was signed off. Any revision removes the signature: you will need to sign again.)")
        old_body = strip_header(current)
        try:
            protected = team_tests(old_body)
        except SyntaxError as e:
            sys.exit(f"{test_file} is not valid Python ({e}). Fix your edits first.")
        prompt = REVISE_PROMPT.format(rules=RULES, conftest=conftest, story_id=story_id,
                                      story=story.get("story", ""), criteria=criteria, current=old_body)
        code, cost = ask_agent(prompt, protected)
        print(f"\nProposed changes (cost ${cost:.4f}):")
        for line in difflib.unified_diff(old_body.splitlines(), code.strip().splitlines(),
                                         f"a/{test_file}", f"b/{test_file}", lineterm=""):
            print(f"  {line}")
        print(f"\nYour team's tests checked unchanged: {', '.join(protected) or 'none yet'}")
        if input("Save this revision? [y/N]: ").strip().lower() != "y":
            sys.exit("Discarded. Your file is unchanged.")
        action = "Revised"
    else:
        # ---- DRAFT: write a first version from the acceptance criteria ----
        if current is not None:
            if approval_status(current) != "unsigned":
                sys.exit(f"{test_file} is signed off. To change it, add '# @TEST-AGENT:' instructions "
                         "and run this script again, or edit it yourselves; then sign it again.")
            if input(f"{test_file} exists. Throw it away and start a new draft? [y/N]: ").strip().lower() != "y":
                sys.exit("Nothing changed. Tip: to change a draft, add '# @TEST-AGENT:' instructions to it.")
        prompt = DRAFT_PROMPT.format(rules=RULES, conftest=conftest, existing=existing_tests(test_file),
                                     story_id=story_id, story=story.get("story", ""), criteria=criteria)
        print(f"Test agent ({MODEL}) is drafting tests for {story_id}...")
        code, cost = ask_agent(prompt, {})
        print(f"Draft cost ${cost:.4f}")
        action = "Drafted"

    # Python, not the model, writes the header, with an empty sign-off line
    with open(test_file, "w") as f:
        f.write(header(story_id, story, action) + code.strip() + "\n")
    report(code, criteria, test_file)
    print(f"\nNext: review {test_file}. To change it, add '# @TEST-AGENT: ...' comments and run this again,")
    print("or edit it yourselves. Add at least one test of your own. Then: python sign_tests.py")