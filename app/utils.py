import re
import json

def extract_json(text):

    if not text:
        return None

    text = text.replace("```json", "").replace("```", "")

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass

    return parse_ui(text)


def parse_ui(text):

    data = {}

    try:
        patterns = {
            "input": r"Query:\s*(\d+)",
            "tg_id": r"Result Tg Id:\s*(\d+)",
            "country": r"Result Country:\s*([^\n•]+)",
            "country_code": r"Result Country Code:\s*(\+\d+)",
            "number": r"Result Number:\s*(\d+)"
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                data[key] = match.group(1).strip()

        data["found"] = True if data.get("number") else False

        if data:
            print("✅ UI PARSED:", data)
            return data

    except Exception as e:
        print("❌ UI parse error:", e)

    return None


def clean_data(data, username):

    if isinstance(data, dict):
    
        data["developer"] = "@captainpapaji"
    return data
