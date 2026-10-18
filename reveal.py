import sys
import hjson
from collections import Counter
from datetime import datetime
from agent_utils import load_latest_backlog, save_next_backlog, append_log

FIBONACCI = [1, 2, 3, 5, 8, 13]
FIT_CODES = {"a": "agent", "p": "pair", "h": "human"}

def ask_cards(prompt, parse):
    while True:
        try:
            cards = [parse(c) for c in input(prompt).split()]
            if cards:
                return cards
        except (ValueError, KeyError):
            pass
        print("  Try again.")

def parse_points(card):
    value = int(card)
    if value not in FIBONACCI:
        raise ValueError
    return value

def most_common(values, cautious_first):
    # Ties go to the more cautious card: the bigger estimate, or more human involvement
    counts = Counter(values)
    top = max(counts.values())
    return next(v for v in cautious_first if counts.get(v) == top)

POINTS_CAUTIOUS = list(reversed(FIBONACCI))
FITS_CAUTIOUS = ["human", "pair", "agent"]

def reasons_to_discuss(team_points, team_fits, agents):
    all_points = team_points + [a["points"] for a in agents.values()]
    all_fits = team_fits + [a["agent_fit"] for a in agents.values()]
    reasons = []
    spread = FIBONACCI.index(max(all_points)) - FIBONACCI.index(min(all_points))
    if spread > 1:
        reasons.append(f"points range from {min(all_points)} to {max(all_points)}")
    if "agent" in all_fits and "human" in all_fits:
        reasons.append("someone says 'agent' and someone says 'human'")
    team_fit = most_common(team_fits, FITS_CAUTIOUS)
    for model, estimate in agents.items():
        if estimate["agent_fit"] != team_fit:
            reasons.append(f"{model.split('/')[-1]} says '{estimate['agent_fit']}', team majority says '{team_fit}'")
    return reasons

if __name__ == "__main__":
    path, version, backlog = load_latest_backlog()
    stories = {s["id"]: s for s in backlog["user_stories"]}
    with open("sealed_estimates.hjson") as f:
        sealed = hjson.load(f)["estimates"]
    with open("reference_stories.hjson") as f:
        references = hjson.load(f)["reference_stories"]

    entries, session = [], datetime.now().isoformat(timespec="minutes")

    # Reference stories were estimated by the team during calibration
    for ref in references:
        story = stories[ref["id"]]
        if story.get("points") is None:
            story["points"], story["agent_fit"] = ref["points"], ref["agent_fit"]
            entries.append((f"ESTIMATED {ref['id']}: {ref['points']} pts, {ref['agent_fit']}",
                            "Calibration: team reference story"))

    for story_id, agents in sealed.items():
        story = stories.get(story_id)
        if story is None or story.get("points") is not None or not agents:
            continue
        print("\n" + "=" * 70)
        print(f"{story_id}: {story.get('title', '')}\n{story.get('story', '')}")
        print(str(story.get("acceptance_criteria", "")).strip())
        print("-" * 70)
        print("Reveal your cards together, then type them in.")
        team_points = ask_cards("Team points cards (e.g. 3 5 3 8), or s to skip: ",
                                lambda c: "skip" if c == "s" else parse_points(c))
        if "skip" in team_points:
            continue
        team_fits = ask_cards("Team agent_fit cards (a/p/h each, e.g. a p p a): ", lambda c: FIT_CODES[c])

        print("\nAGENT CARDS")
        for model, e in agents.items():
            print(f"  {model.split('/')[-1]}: {e['points']} points, {e['agent_fit']}")
            print(f"    reasoning: {e.get('reasoning', '')}")
            for risk in e.get("risks", []):
                print(f"    risk: {risk}")
            print(f"    files: {', '.join(e.get('files_likely_touched', []))}")

        reasons = reasons_to_discuss(team_points, team_fits, agents)
        if reasons:
            print("\nDISCUSS before agreeing:")
            for r in reasons:
                print(f"  - {r}")

        default_points = most_common(team_points, POINTS_CAUTIOUS)
        default_fit = most_common(team_fits, FITS_CAUTIOUS)
        while True:
            answer = input(f"Agreed points [{default_points}]: ").strip()
            if not answer:
                points = default_points
                break
            if answer.isdigit() and int(answer) in FIBONACCI:
                points = int(answer)
                break
        while True:
            answer = input(f"Agreed agent_fit a/p/h [{default_fit[0]}]: ").strip()
            if not answer or answer in FIT_CODES:
                fit = FIT_CODES.get(answer, default_fit)
                break

        story["points"], story["agent_fit"] = points, fit
        entries.append((f"ESTIMATED {story_id}: {points} pts, {fit}", "Planning poker: team decision"))
        append_log("estimates.hjson", {
            "session": session, "story_id": story_id,
            "team_points": team_points, "team_fits": team_fits,
            "agents": {m: {"points": e["points"], "agent_fit": e["agent_fit"]} for m, e in agents.items()},
            "discussed": reasons, "agreed_points": points, "agreed_fit": fit,
        })

    if not entries:
        sys.exit("\nNothing estimated. Backlog unchanged.")
    out = save_next_backlog(backlog, version, entries)
    print(f"\nSaved {len(entries)} estimates to {out}. Card history logged in estimates.hjson.")