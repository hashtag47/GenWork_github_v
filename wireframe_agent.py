import os
import re
import glob
from datetime import datetime
import hjson
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path

load_dotenv()
client = OpenAI(
  api_key=os.environ.get("REQUESTY_API_KEY"),
  base_url="https://router.requesty.ai/v1"
)

def get_input_file():
    files = glob.glob("backlog*.hjson")
    max_v = 0
    latest_file = "backlog.hjson"

    for f in files:
        match = re.search(r"backlog_[vV](\d+)\.hjson", f)
        if match:
            v = int(match.group(1))
            if v > max_v:
                max_v = v
                latest_file = f

    if max_v == 0 and "backlog.hjson" not in files:
        print("Warning: No backlog files found in current directory.")

    user_input = input(f"Enter input backlog file [{latest_file}]: ").strip()
    return user_input if user_input else latest_file

# type hints in Python: ->
def load_system_prompt(path: str="prompts/wireframe_agent_prompt.txt") -> str:
    return Path(path).read_text(encoding="utf-8")

def generate_story_map(backlog_content):
    print("Wireframe Agent is visualizing the Product Backlog...")

    system_prompt = load_system_prompt()

    # Using GPT-5.6 Luna for massive context capacity and rapid HTML generation
    response = client.chat.completions.create(
        model="openai/gpt-5.6-luna",
        messages=[
            {"role":"system", "content":system_prompt},
            {"role":"user", "content":backlog_content}
        ],
        temperature=0.4 #Higher temperature for creative HTML/CSS generation
    )
    return response.choices[0].message.content

if __name__ == "__main__":
    input_filename = get_input_file()

    if not os.path.exists(input_filename):
        print(f"Error: Could not find {input_filename}")
        exit(1)
      
    with open(input_filename, "r") as f:
        backlog_data = f.read()

    html_output = generate_story_map(backlog_data)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_filename = f"wireframe_{timestamp}.html"

    with open(output_filename, "w") as f:
        f.write(html_output)

    print(f"Success! Open {output_filename} in your browser.")