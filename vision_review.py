import os
import sys
import base64
import hjson
from agent_utils import ask_hjson

MODEL = "anthropic/claude-sonnet-5"  # must accept image input

PROMPT = """You are a UX designer reviewing a wireframe that a human has marked up with a red pen.
The image is a screenshot of the wireframe with RED ink drawn on it. The HTML source of the
wireframe is included below.

List every change the red ink asks for, one item per mark. Do NOT suggest improvements of your
own: report only what the red ink says. If a mark is ambiguous, still list it, set confidence to
low and explain the ambiguity in 'unclear'.

Return ONLY HJSON in exactly this form, one field per line:
{
  changes: [
    {
      where: "Which element the mark is on, e.g. the 'Save' button in the top bar"
      change: "What the mark asks for, e.g. Remove this button"
      confidence: high
      unclear: ""
    }
  ]
}

WIREFRAME HTML:
"""

if __name__ == "__main__":
    image_file = input("Red-pen image [assets/wireframe_markup.png]: ").strip() or "assets/wireframe_markup.png"
    html_file = input("Wireframe HTML [wireframe.html]: ").strip() or "wireframe.html"
    for f in (image_file, html_file):
        if not os.path.exists(f):
            sys.exit(f"Error: could not find {f}")

    with open(image_file, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()
    with open(html_file) as f:
        html_source = f.read()

    messages = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT + html_source},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
    ]}]
    print("Vision agent is reading your red pen...")
    result, cost = ask_hjson(MODEL, messages, max_tokens=1500)

    # Python, not the model, numbers the changes and marks them all as unreviewed
    changes = []
    for i, item in enumerate(result.get("changes", []), start=1):
        changes.append({"id": i, "status": "proposed", **{k: item.get(k, "") for k in ("where", "change", "confidence", "unclear")}})

    with open("wireframe_changes.hjson", "w") as f:
        f.write(hjson.dumps({"source_html": html_file, "markup": image_file, "changes": changes}))

    print(f"\nThe agent read {len(changes)} changes (cost ${cost:.4f}):\n")
    for c in changes:
        print(f"  {c['id']}. [{c['confidence']}] {c['where']}: {c['change']}")
        if c["unclear"]:
            print(f"     unclear: {c['unclear']}")
    print("\nNow open wireframe_changes.hjson. For EVERY change, set status to approved or rejected.")
    print("Fix any wording the agent got wrong, and add any mark it missed (with status: approved).")