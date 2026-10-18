import os
import re
import sys
import glob
import difflib
import hjson
from agent_utils import client, call_cost, strip_fences, load_system_prompt

MODEL = "anthropic/claude-sonnet-5"

PROMPT = load_system_prompt("prompts/apply_wireframe_changes_prompts.txt")

def next_wireframe_name():
    versions = [int(m.group(1)) for f in glob.glob("wireframe_v*.html")
                if (m := re.fullmatch(r"wireframe_v(\d+)\.html", os.path.basename(f)))]
    return f"wireframe_v{max(versions + [1]) + 1}.html"

if __name__ == "__main__":
    with open("wireframe_changes.hjson") as f:
        review = hjson.load(f)

    undecided = [c["id"] for c in review["changes"] if c.get("status") not in ("approved", "rejected")]
    if undecided:
        sys.exit(f"Not yet reviewed: changes {undecided}. Set each status to approved or rejected first.")
    approved = [c for c in review["changes"] if c["status"] == "approved"]
    if not approved:
        sys.exit("No approved changes. Nothing to do.")

    with open(review["source_html"]) as f:
        old_html = f.read()
    change_list = "\n".join(f"{i}. {c['where']}: {c['change']}" for i, c in enumerate(approved, start=1))

    print(f"Applying {len(approved)} approved changes to {review['source_html']}...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT.format(changes=change_list, html=old_html)}],
        max_tokens=8000,
        temperature=0.2,
    )
    new_html = strip_fences(response.choices[0].message.content)

    out = next_wireframe_name()
    with open(out, "w") as f:
        f.write(new_html)

    # How much did the agent actually change? Compare with the number of changes you approved.
    diff = list(difflib.unified_diff(old_html.splitlines(), new_html.splitlines(), lineterm=""))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    print(f"Saved {out}: {added} lines added, {removed} removed (cost ${call_cost(MODEL, response):.4f}).")
    print(f"Open it in your browser. Another round? Mark up a new screenshot and run vision_review.py on {out}.")