import os
import re
import sys
import copy
import glob
import secrets
import hjson
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path

load_dotenv()
client = OpenAI(api_key=os.environ.get("REQUESTY_API_KEY"), base_url="https://router.requesty.ai/v1")

def read_file(filename):
    with open(filename, "r") as file:
        return file.read()

def get_file_versions():
    # Find all backlog files
    files = glob.glob("backlog*.hjson")
    max_v = 0
    latest_file = "backlog.hjson"
    
    for f in files:
        match = re.search(r"backlog_v(\d+)\.hjson", f)
        if match:
            v = int(match.group(1))
            if v > max_v:
                max_v = v
                latest_file = f
    
    if max_v == 0 and "backlog.hjson" not in files:
        print("Warning: No backlog files found in current directory.")
        
    # Auto-suggest the highest versioned file found
    user_input = input(f"Enter input backlog file [{latest_file}]: ").strip()
    input_file = user_input if user_input else latest_file
    
    # Increment for the new output file
    out_v = max_v + 1 if max_v > 0 else 2
    out_file = f"backlog_v{out_v}.hjson"
    
    return input_file, out_file

def strip_fences(text):
    # Models sometimes wrap output in ```hjson fences despite instructions
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n", "", text)
    return re.sub(r"\n```\s*$", "", text)

def load_system_prompt(path: str="prompts/iterate_backlog_prompt.txt") -> str:
    return Path(path).read_text(encoding="utf-8")

def request_changeset(pitch_content, current_backlog, retries=1):
    SYSTEM_PROMPT = load_system_prompt()
    print("\nAgent is reading your @PO-AGENT directives and preparing a change set...")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"ORIGINAL PITCH:\n{pitch_content}\n\nCURRENT BACKLOG WITH DIRECTIVES:\n{current_backlog}"}
    ]
    for attempt in range(retries + 1):
        response = client.chat.completions.create(
            model="anthropic/claude-sonnet-5",
            messages=messages,
            temperature=0.2
        )
        raw = strip_fences(response.choices[0].message.content)
        try:
            changes = hjson.loads(raw)
            for key in ("updated_stories", "new_stories", "deleted_stories", "unaddressed_directives"):
                if not isinstance(changes.get(key, []), list):
                    raise ValueError(f"'{key}' must be a list")
            return changes
        except Exception as e:
            print(f"Attempt {attempt + 1}: invalid change set ({e}).")
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your output was invalid: {e}. Return ONLY the corrected HJSON change set."}
            ]
    sys.exit("Error: the agent did not return a valid change set. Nothing was saved.")

def new_id(title, taken):
    # Python, not the LLM, generates new ids, so they are guaranteed unique
    base = re.sub(r"[^a-z0-9]+", "_", str(title).lower()).strip("_")[:24] or "story"
    while True:
        candidate = f"{base}_{secrets.token_hex(2)}"
        if candidate not in taken:
            return candidate

def cited(item):
    return item.get("directive") or "!! NO DIRECTIVE CITED"

PROTECTED_FIELDS = ("points", "notes")  # owned by the human team, never the agent

def apply_changes(old_backlog, changes, version):
    backlog = copy.deepcopy(old_backlog)
    changelog = list(backlog.pop("_changelog", []))
    backlog.pop("_iteration_summary", None)
    stories = backlog["user_stories"]
    by_id = {s["id"]: s for s in stories}
    touched, log = set(), []

    def record(symbol, change, directive):
        log.append(f"{symbol} {change}\n    directive: {directive}")
        changelog.append({"version": version, "change": change, "directive": directive})

    # 1. Updates: only existing stories, only the fields the agent sent
    for item in changes.get("updated_stories", []):
        fields = dict(item)
        sid = fields.pop("id", None)
        directive = cited(fields)
        fields.pop("directive", None)
        for key in PROTECTED_FIELDS:
            fields.pop(key, None)
        if sid not in by_id:
            log.append(f"! IGNORED update to unknown id '{sid}'")
            continue
        story = by_id[sid]
        changed = [k for k, v in fields.items() if story.get(k) != v]
        story.update(fields)
        touched.add(sid)
        record("~", f"CHANGED {sid} ({', '.join(changed) or 'no actual change'})", directive)

    # 2. Deletions (including the originals of split stories)
    for item in changes.get("deleted_stories", []):
        sid = item.get("id")
        if sid not in by_id:
            log.append(f"! IGNORED deletion of unknown id '{sid}'")
            continue
        stories.remove(by_id.pop(sid))
        touched.add(sid)
        record("-", f"DELETED {sid}", cited(item))

    # 3. New stories, with ids assigned here and protected fields left empty
    for item in changes.get("new_stories", []):
        fields = dict(item)
        directive = cited(fields)
        fields.pop("directive", None)
        fields.pop("id", None)
        fields["points"] = None
        fields["notes"] = []
        fields.setdefault("open_questions", [])
        sid = new_id(fields.get("title", "story"), by_id)
        story = {"id": sid, **fields}
        stories.append(story)
        by_id[sid] = story
        touched.add(sid)
        record("+", f"ADDED {sid}: {fields.get('title', '')}", directive)

    # 4. Directives the agent could not carry out are recorded too
    for item in changes.get("unaddressed_directives", []):
        record("?", "NOT DONE", str(item))

    untouched = sum(1 for s in stories if s["id"] not in touched)
    summary = changes.get("summary", "No summary provided.")
    # Changelog and summary go at the top of the file, where people will see them
    new_backlog = {"_changelog": changelog, "_iteration_summary": summary, **backlog}
    return new_backlog, log, untouched

if __name__ == "__main__":
    input_file, output_file = get_file_versions()
    
    if not os.path.exists(input_file):
        print(f"Error: Could not find {input_file}")
        exit(1)
        
    current_hjson = read_file(input_file)
    directive_count = current_hjson.count("@PO-AGENT:")
    if directive_count == 0:
        print("No # @PO-AGENT: directives found. Nothing to do.")
        sys.exit(0)

    try:
        old_backlog = hjson.loads(current_hjson)
    except Exception as e:
        sys.exit(f"Error: {input_file} is not valid HJSON (check your edits). {e}")

    print(f"Reading {input_file} ({directive_count} directives)...")
    pitch = read_file("pitch.md") # Pointing to the real pitch.md
    changes = request_changeset(pitch, current_hjson)
    version = output_file.replace(".hjson", "")
    new_backlog, log, untouched = apply_changes(old_backlog, changes, version)

    # Show the human EXACTLY what will change before anything is saved
    print("\n--- PO Agent Change Set ---")
    print(changes.get("summary", "No summary provided."))
    for line in log:
        print(line)
    print(f"= {untouched} stories untouched")
    print("---------------------------\n")

    if input(f"Save as {output_file}? [y/N]: ").strip().lower() != "y":
        print("Discarded. Nothing was saved.")
        sys.exit(0)

    with open(output_file, "w") as file:
        file.write(hjson.dumps(new_backlog))
        
    print(f"Success! Saved new iteration to {output_file}")