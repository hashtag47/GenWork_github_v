import os
import sys
import hjson
from agent_utils import ask_hjson, load_latest_backlog, is_ready, load_system_prompt

# Llama died
ESTIMATORS = ["anthropic/claude-sonnet-5", "openai/gpt-6.1-sol"]
FIBONACCI = [1, 2, 3, 5, 8, 13]
FITS = ["agent", "pair", "human"]
SKIP_DIRS = {"venv", ".git", "__pycache__", "instance", ".pytest_cache"}

PROMPT = load_system_prompt("prompts/estimate_agent_prompt.txt")

def file_tree():
    paths = []
    for folder, dirs, files in os.walk("."):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith((".py", ".sql", ".html", ".css", ".js")):
                paths.append(os.path.relpath(os.path.join(folder, name)))
    return "\n".join(paths)

def describe(story):
    return hjson.dumps({k: story.get(k) for k in ("title", "story", "acceptance_criteria")})

def valid(estimate):
    return estimate.get("points") in FIBONACCI and estimate.get("agent_fit") in FITS

if __name__ == "__main__":
    path, version, backlog = load_latest_backlog()
    stories = {s["id"]: s for s in backlog["user_stories"]}

    with open("reference_stories.hjson") as f:
        references = hjson.load(f)["reference_stories"]
    missing = [r["id"] for r in references if r["id"] not in stories]
    if missing:
        sys.exit(f"Error: reference stories not found in {path}: {missing}")

    anchor_text = "\n\n".join(
        f"{describe(stories[r['id']])}\nTEAM ESTIMATE: {r['points']} points, agent_fit {r['agent_fit']} ({r.get('why', '')})"
        for r in references
    )
    reference_ids = {r["id"] for r in references}
    to_estimate = [s for s in backlog["user_stories"]
                   if is_ready(s) and s.get("points") is None and s["id"] not in reference_ids]
    if not to_estimate:
        sys.exit("No ready, unestimated stories. Run ready_check.py.")

    print(f"Estimating {len(to_estimate)} ready stories from {path} with {len(ESTIMATORS)} models.")
    print("Estimates are sealed: they will not be shown until reveal.py.\n")

    sealed, total_cost = {}, 0.0
    tree = file_tree()
    for story in to_estimate:
        sealed[story["id"]] = {}
        for model in ESTIMATORS:
            prompt = PROMPT.format(reference_stories=anchor_text, file_tree=tree, story=describe(story))
            try:
                estimate, cost = ask_hjson(model, [{"role": "user", "content": prompt}], max_tokens=600)
                total_cost += cost
                if not valid(estimate):
                    raise ValueError(f"invalid points or agent_fit: {estimate.get('points')}, {estimate.get('agent_fit')}")
                sealed[story["id"]][model] = estimate
                print(f"  sealed  {story['id']:<28} {model}")
            except Exception as e:
                print(f"  FAILED  {story['id']:<28} {model}: {e}")

    with open("sealed_estimates.hjson", "w") as f:
        f.write(hjson.dumps({"backlog": path, "estimates": sealed}))

    print(f"\nSaved sealed_estimates.hjson. Total cost: ${total_cost:.4f}")
    print("Do NOT open that file. Play your cards first, then run reveal.py.")