import os
import time
from typing import Literal
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from axe_playwright_python.sync_playwright import Axe
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError

load_dotenv()

SCOPED_AXE_RULES = {"color-contrast", "button-name", "link-name", "label"}

# 1. Test Playwright + axe-core (filtered to your 4 scoped rules)
print("1/2 Testing Playwright + axe-core...")
SAMPLE_HTML = """
<html lang="en">
  <head><title>Promo Modal</title></head>
  <body style="background:#ffffff; font-family:sans-serif; padding:40px;">
    <main>
      <h1>Get 20% Off Your First Order!</h1>
      <button style="background:#005fcc; color:#ffffff; padding:12px 24px; font-size:16px;">
        Claim My 20% Discount
      </button>
      <br><br>
      <a href="#close" style="color:#cccccc; font-size:11px;">
        No thanks, I prefer paying full price
      </a>
    </main>
  </body>
</html>
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.set_content(SAMPLE_HTML)

    axe = Axe()
    results = axe.run(page)
    violations = results.response.get("violations", [])
    scoped_hits = [v["id"] for v in violations if v["id"] in SCOPED_AXE_RULES]
    print(f"    Scoped axe-core violations detected: {scoped_hits}")
    browser.close()

# 2. Test Google Gemini API with automatic retry for 503 / 429 errors
print("2/2 Testing Google Gemini API...")

class QuickCheck(BaseModel):
    rationale: str
    predicted_category: Literal[
        "preselected_marketing_consent",
        "confirmshaming",
        "visually_downplayed_rejection",
        "none",
        "uncertain",
    ]

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def generate_with_retry(model_id: str, prompt: str, max_retries: int = 4):
    for attempt in range(1, max_retries + 1):
        try:
            return client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    seed=42,
                    response_mime_type="application/json",
                    response_schema=QuickCheck,
                ),
            )
        except (ServerError, ClientError) as e:
            if attempt == max_retries:
                raise
            wait_seconds = 5 * (2 ** (attempt - 1))
            print(f"    [{model_id}] Temporary API error ({e.code}). Retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)

prompt = (
    "Classify this decline link paired with a primary accept button: "
    "'No thanks, I prefer paying full price' (11px #cccccc text on #ffffff)."
)

# Use gemini-3.5-flash-lite (high free-tier quota & low 503 rate) or gemini-3.8-flash
resp = generate_with_retry("gemini-3.5-flash-lite", prompt)
print(f"    API structured response: {resp.text}")
print("\nAll thesis tools are installed and ready!")