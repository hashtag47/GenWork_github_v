import os
import re
import ast
import glob
import hashlib
import hjson
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path

load_dotenv()
client = OpenAI(api_key=os.environ.get("REQUESTY_API_KEY"), base_url="https://router.requesty.ai/v1")

# USD per 1M tokens (input, output). Check the Requesty Model Library for current prices.
PRICES = {
    "anthropic/claude-sonnet-5": (2.00, 10.00),
    "nebius/meta-llama/Llama-3.3-70B-Instruct": (0.13, 0.40),
    "openai/gpt-5.6-luna": (1.00, 6.00),
}

def call_cost(model, response):
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    usage = response.usage
    return usage.prompt_tokens / 1_000_000 * price_in + usage.completion_tokens / 1_000_000 * price_out

def strip_fences(text):
    # Models sometimes wrap output in ``` fences despite instructions
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n", "", text)
    return re.sub(r"\n```\s*$", "", text)

def ask_hjson(model, messages, max_tokens=1500, retries=1):
    """Call a model, parse its HJSON reply, retry once with the error. Returns (data, cost)."""
    messages = list(messages)
    total = 0.0
    for attempt in range(retries + 1):
        response = client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, temperature=0.2
        )
        total += call_cost(model, response)
        raw = strip_fences(response.choices[0].message.content)
        try:
            return hjson.loads(raw), total
        except Exception as e:
            print(f"  {model}: invalid HJSON on attempt {attempt + 1} ({e})")
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your output was invalid HJSON: {e}. Return ONLY corrected HJSON, one field per line."},
            ]
    raise ValueError(f"{model} did not return valid HJSON")

# ---------- Backlog versioning (same scheme as iterate_backlog.py) ----------

def load_system_prompt(path: str="prompts/iterate_backlog_prompt.txt") -> str:
    return Path(path).read_text(encoding="utf-8")

def find_latest_backlog():
    path, version = "backlog.hjson", 1
    for f in glob.glob("backlog_v*.hjson"):
        match = re.fullmatch(r"backlog_v(\d+)\.hjson", os.path.basename(f))
        if match and int(match.group(1)) > version:
            path, version = f, int(match.group(1))
    return path, version

def load_latest_backlog():
    path, version = find_latest_backlog()
    with open(path) as f:
        return path, version, hjson.load(f)

def save_next_backlog(backlog, version, entries):
    """Write backlog_v(N+1).hjson, recording each (change, reason) in the _changelog."""
    out = f"backlog_v{version + 1}.hjson"
    backlog = dict(backlog)
    changelog = list(backlog.pop("_changelog", []))
    for change, reason in entries:
        changelog.append({"version": out.replace(".hjson", ""), "change": change, "directive": reason})
    with open(out, "w") as f:
        f.write(hjson.dumps({"_changelog": changelog, **backlog}))
    return out

def is_ready(story):
    """Definition of Ready: acceptance criteria written, no open questions."""
    return bool(str(story.get("acceptance_criteria", "")).strip()) and not story.get("open_questions")

# ---------- Test files: directives, team tests and sign-off ----------

APPROVED_LINE = re.compile(r"^# APPROVED-BY:(.*)$", re.MULTILINE)
DIRECTIVE = re.compile(r"^[ \t]*#[ \t]*@TEST-AGENT:[ \t]*(.+)$", re.MULTILINE)

def fingerprint(test_source):
    """A short hash of the file's content, ignoring the APPROVED-BY line itself."""
    body = APPROVED_LINE.sub("", test_source)
    normalised = "\n".join(line.rstrip() for line in body.splitlines()).strip()
    return hashlib.sha256(normalised.encode()).hexdigest()[:12]

def approval_status(test_source):
    """'valid' if signed with sign_tests.py and unchanged since; 'stale' if edited after
    signing; 'unsigned' otherwise (including names typed in by hand)."""
    match = APPROVED_LINE.search(test_source)
    signed = re.search(r"fingerprint ([0-9a-f]{12})\s*$", match.group(1)) if match else None
    if not signed:
        return "unsigned"
    return "valid" if signed.group(1) == fingerprint(test_source) else "stale"

def is_approved(test_source):
    return approval_status(test_source) == "valid"

def find_directives(test_source):
    return DIRECTIVE.findall(test_source)

def team_tests(test_source):
    """Tests the team wrote themselves: {name: exact text}, found by an '# ADDED BY TEAM'
    comment directly above the test (the comment block is part of the text)."""
    lines = test_source.splitlines()
    found = {}
    for node in ast.parse(test_source).body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            top = start
            while top > 0 and lines[top - 1].strip().startswith("#"):
                top -= 1
            comments = lines[top:start]
            if any("ADDED BY TEAM" in c for c in comments):
                found[node.name] = "\n".join(l.rstrip() for l in lines[top:node.end_lineno])
    return found

def append_log(filename, entry):
    """Append one entry to an HJSON log file (a list), creating it if needed."""
    entries = []
    if os.path.exists(filename):
        with open(filename) as f:
            entries = hjson.load(f)
    entries.append(entry)
    with open(filename, "w") as f:
        f.write(hjson.dumps(entries))