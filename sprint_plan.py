import sys
from agent_utils import load_latest_backlog, save_next_backlog, is_ready

path, version, backlog = load_latest_backlog()
stories = {s["id"]: s for s in backlog["user_stories"]}
candidates = [s for s in backlog["user_stories"] if is_ready(s) and s.get("points") is not None]

print(f"Ready and estimated stories in {path}:\n")
for s in candidates:
    print(f"  {s['id']:<28} {s['points']:>2} pts  {s.get('agent_fit', '?'):<6} {s.get('title', '')}")

capacity = int(input("\nSprint 1 capacity in points [12]: ").strip() or 12)
chosen = [i.strip() for i in input("Story ids to commit, highest priority first (comma separated): ").split(",") if i.strip()]

bad = [i for i in chosen if i not in stories or stories[i] not in candidates]
if bad:
    sys.exit(f"Error: not ready or not estimated: {bad}")

total = sum(stories[i]["points"] for i in chosen)
print(f"\nCommitting {len(chosen)} stories, {total} points (capacity {capacity}).")
if total > capacity and input("That is over capacity. Commit anyway? [y/N]: ").strip().lower() != "y":
    sys.exit("Nothing saved.")

goal = input("Sprint goal (one sentence): ").strip()
entries = []
for s in backlog["user_stories"]:
    if s["id"] in chosen and s.get("sprint") != "Sprint 1":
        s["sprint"] = "Sprint 1"
        entries.append((f"MOVED {s['id']} into Sprint 1", "Sprint planning: team commitment"))
    elif s["id"] not in chosen and s.get("sprint") == "Sprint 1":
        s["sprint"] = "Backlog"
        entries.append((f"MOVED {s['id']} out of Sprint 1", "Sprint planning: not committed"))

backlog["sprint_1"] = {"goal": goal, "capacity": capacity, "committed": chosen, "committed_points": total}
entries.append((f"COMMITTED Sprint 1: {total} pts, goal: {goal}", "Sprint planning: team commitment"))
print(f"Saved {save_next_backlog(backlog, version, entries)}")