import argparse
import csv
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError

load_dotenv(override=True)
api_key = os.getenv("GEMINI_API_KEY", "").strip()
if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing in .env. Save your active AI Studio key first.")

client = genai.Client(api_key=api_key)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class ControlFinding(BaseModel):
    target_control_text: str = Field(
        description="Visible text or description of the primary interactive control being evaluated."
    )
    visual_prominence_check: str = Field(
        description="Observable comparison of size, fill, contrast, and style against paired controls."
    )
    textual_tone_check: str = Field(
        description="Observable check for guilt-inducing, self-deprecating, or promotional marketing terms."
    )
    state_and_label_check: str = Field(
        description="Observable check of default checked/on state and associated visible label text."
    )
    rationale: str = Field(
        description="Concise objective rationale citing observable visual/textual evidence only."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    predicted_category: Literal[
        "preselected_marketing_consent",
        "confirmshaming",
        "visually_downplayed_rejection",
        "none",
        "uncertain",
    ]


class ScreenshotTrialResult(BaseModel):
    primary_finding: ControlFinding
    additional_findings: list[ControlFinding] = Field(
        default_factory=list,
        description="Any secondary controls in the same screenshot exhibiting one of the three patterns.",
    )


SYSTEM_PROMPT = """
You are an objective web UI inspection classifier conducting proof-of-concept trials on desktop web screenshots.
Examine the visible interactive controls, text, default control states, and surrounding dialog/form context
using ONLY observable visual and textual criteria:

1. preselected_marketing_consent: A checkbox or toggle is visibly checked/on at initial display AND its
   associated label contains promotional, newsletter, or marketing-related terms.
2. confirmshaming: A decline/rejection option is paired with an acceptance option in the same dialog or form,
   AND the decline wording uses guilt-inducing, self-deprecating, or emotionally loaded language compared
   with neutral decline wording.
3. visually_downplayed_rejection: A rejection control paired with an acceptance control is visibly less
   prominent (substantially smaller dimensions, muted/low contrast, or plain text link presentation vs. a
   filled primary button).
4. none: Normal interface controls with none of the three patterns above.
5. uncertain: Cropped, blurry, or genuinely ambiguous visual/textual evidence.

Do NOT infer designer intent, legal compliance, or psychological effects. Cite only observable evidence.
"""


def natural_sort_key(path: Path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def analyze_image_with_retry(model_id: str, img_path: Path) -> ScreenshotTrialResult:
    with Image.open(img_path) as im:
        rgb_img = im.convert("RGB")

    prompt = (
        f"Inspect the web interface screenshot '{img_path.name}'. Identify the primary interactive control "
        "of interest (and any secondary deceptive controls if multiple exist) and classify using the rubric."
    )

    for attempt in range(1, 5):
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents=[prompt, rgb_img],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.0,
                    seed=42,
                    response_mime_type="application/json",
                    response_schema=ScreenshotTrialResult,
                ),
            )
            return ScreenshotTrialResult.model_validate_json(resp.text)
        except (ServerError, ClientError) as e:
            if isinstance(e, ClientError) and e.code != 429:
                raise
            if attempt == 4:
                raise
            wait = 5 * (2 ** (attempt - 1))
            print(f"    API rate-limited/busy ({e.code}), retrying in {wait}s...")
            time.sleep(wait)


def escape_md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default="trial_screenshots", help="Folder containing your screenshots")
    parser.add_argument("--model", default="gemini-3.5-flash-lite", help="Gemini model ID")
    parser.add_argument("--runs", type=int, default=3, help="Runs per screenshot (default: 3)")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        print(f"Created '{folder}/'. Put your 9 screenshots inside it and re-run this script.")
        return

    images = sorted([p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS], key=natural_sort_key)
    if not images:
        print(f"No images (.png, .jpg, .jpeg, .webp) found in '{folder}/'.")
        return

    print(f"\nRunning Proof-of-Concept Trial on {len(images)} screenshot(s) using '{args.model}' (runs={args.runs})...\n")
    print(f"{'Screenshot':16s} | {'Model Label':29s} | {'Votes':5s} | {'Conf':4s} | {'Target Control':26s} | {'Rationale'}")
    print("-" * 145)

    json_records = []
    csv_rows = []
    md_lines = [
        f"# Proof-of-Concept Screenshot Trial Log (`{args.model}`, {args.runs} runs/image)\n",
        "| Screenshot | Target Control | Model Label (Majority Vote) | Votes | Confidence | Visual Prominence Check | Textual Tone Check | State & Label Check | Rationale |",
        "| :--- | :--- | :--- | :---: | :---: | :--- | :--- | :--- | :--- |",
    ]

    for img_path in images:
        run_results = []
        for _ in range(args.runs):
            run_results.append(analyze_image_with_retry(args.model, img_path))
            time.sleep(1.5)

        labels = [r.primary_finding.predicted_category for r in run_results]
        top_label, top_count = Counter(labels).most_common(1)[0]
        majority_needed = (args.runs // 2) + 1
        final_label = top_label if top_count >= majority_needed else "uncertain"

        chosen = next(
            (r for r in run_results if r.primary_finding.predicted_category == final_label),
            run_results[0],
        )
        pf = chosen.primary_finding
        vote_ratio = f"{top_count}/{args.runs}"

        print(
            f"{img_path.name:16s} | {final_label:29s} | {vote_ratio:5s} | {pf.confidence:4.2f} | "
            f"{pf.target_control_text[:26]:26s} | {pf.rationale}"
        )

        json_records.append(
            {
                "screenshot": img_path.name,
                "model_id": args.model,
                "runs": args.runs,
                "run_votes": labels,
                "model_label": final_label,
                "target_control": pf.target_control_text,
                "confidence": pf.confidence,
                "visual_prominence_check": pf.visual_prominence_check,
                "textual_tone_check": pf.textual_tone_check,
                "state_and_label_check": pf.state_and_label_check,
                "rationale": pf.rationale,
            }
        )

        csv_rows.append(
            {
                "screenshot": img_path.name,
                "target_control": pf.target_control_text,
                "model_label": final_label,
                "votes": vote_ratio,
                "confidence": f"{pf.confidence:.2f}",
                "rationale": pf.rationale,
            }
        )

        md_lines.append(
            f"| `{escape_md(img_path.name)}` | {escape_md(pf.target_control_text)} | **{escape_md(final_label)}** | "
            f"{vote_ratio} | {pf.confidence:.2f} | {escape_md(pf.visual_prominence_check)} | "
            f"{escape_md(pf.textual_tone_check)} | {escape_md(pf.state_and_label_check)} | {escape_md(pf.rationale)} |"
        )

    Path("trial_results.json").write_text(json.dumps(json_records, indent=2), encoding="utf-8")
    Path("trial_log_table.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    with Path("trial_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    print("-" * 145)
    print("Saved log tables: trial_log_table.md, trial_results.csv, trial_results.json")


if __name__ == "__main__":
    main()