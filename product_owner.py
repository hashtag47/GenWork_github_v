import os
import re
import hjson
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path # standard library

load_dotenv()
client = OpenAI(
  api_key=os.environ.get("REQUESTY_API_KEY"),
  base_url="https://router.requesty.ai/v1"
)

def read_pitch(filename="pitch.md"):
    with open(filename, "r", encoding="utf-8") as file:
        return file.read()

# type hints in Python: ->
def load_system_prompt(path: str="prompts/system_prompt.txt") -> str:
    return Path(path).read_text(encoding="utf-8")
    
def generate_backlog(pitch_content, model="anthropic/claude-sonnet-5"):
    print(f"Generating backlog using {model}...")

    system_prompt = load_system_prompt()
    # python dictionary is a collection of key–value pairs
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": pitch_content}
        ],
        temperature=0.2
    )

    return response

# Execution
# In Python, there’s no entry point.
# only run this part if this file is the one being run, not imported
if __name__ == "__main__":
    pitch = read_pitch()
    # model_choice = "openai/gpt-5.6-luna"
    model_choice = "gemini-4-argon"
    # model_choice = "anthropic/claude-sonnet-5"
    response_obj = generate_backlog(pitch, model=model_choice)
    raw_hjson = response_obj.choices[0].message.content

    print(response_obj.model_dump_json(indent=2))

    # Sanitize the model name to prevent file path errors
    safe_model = re.sub(r'[^a-zA-Z0-9_-]', "_", model_choice)
    file_name = f"backlog_{safe_model}.hjson"

    # Save the raw output
    with open(file_name, "w", encoding="utf-8") as file:
        file.write(raw_hjson)

    # Verify it parses correctly
    try:
        parsed_data = hjson.loads(raw_hjson)
        stories = parsed_data.get('user_stories', [])
        questions = sum(len(s.get('open_questions', [])) for s in stories)
        print(f"Success! {file_name} generated with {len(stories)} stories and {questions} open questions.")
        
        # --- NEW: TOKEN ECONOMICS ---
        usage = response_obj.usage
        in_tok = usage.prompt_tokens
        out_tok = usage.completion_tokens
        
        # Pricing for Claude Sonnet 5: $2.00 per 1M input, $10.00 per 1M output
        cost = (in_tok / 1000000 * 2.00) + (out_tok / 1000000 * 10.00)
        
        print(f"Tokens: {in_tok} in, {out_tok} out")
        print(f"Generation Cost: ${cost:.5f}")
    except Exception as e:
        print("Error: The LLM failed to return valid HJSON.", e)

# questions = 0
# for s in stories:
#     questions += len(s.get('open_questions', []))