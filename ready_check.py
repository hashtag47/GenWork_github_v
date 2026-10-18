from agent_utils import load_latest_backlog, is_ready

path, version, backlog = load_latest_backlog()
print(f"Definition of Ready check on {path}\n")

ready = [s for s in backlog["user_stories"] if is_ready(s)]
blocked = [s for s in backlog["user_stories"] if not is_ready(s)]

for story in blocked:
    print(f"NOT READY  {story['id']}: {story.get('title', '')}")
    if not str(story.get("acceptance_criteria", "")).strip():
        print("           ! no acceptance criteria")
    for question in story.get("open_questions", []):
        print(f"           ? {question}")

print()
for story in ready:
    print(f"READY      {story['id']}: {story.get('title', '')}")

print(f"\n{len(ready)} ready, {len(blocked)} not ready.")