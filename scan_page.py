import argparse
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from axe_playwright_python.sync_playwright import Axe
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

SCOPED_AXE_RULES = {"color-contrast", "button-name", "link-name", "label"}


class ControlPrediction(BaseModel):
    visual_prominence_check: str = Field(
        description="Size, fill, contrast, and style comparison against sibling controls."
    )
    textual_tone_check: str = Field(
        description="Presence of guilt-inducing, self-deprecating, or promotional marketing terms."
    )
    state_and_label_check: str = Field(
        description="Default checked/on state and associated visible/surrounding label text."
    )
    rationale: str = Field(
        description="Objective rationale citing observable visual/textual evidence only."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    predicted_category: Literal[
        "preselected_marketing_consent",
        "confirmshaming",
        "visually_downplayed_rejection",
        "none",
        "uncertain",
    ]


SYSTEM_PROMPT = """
You are an objective web UI inspection classifier. Evaluate the highlighted target control
(outlined in magenta in Image 2) strictly using observable visual, textual, and structural criteria:

1. preselected_marketing_consent: A checkbox or toggle is in the checked/on state at page load
   without prior user interaction, AND its associated or surrounding label text contains
   promotional, newsletter, or marketing-related terms.
2. confirmshaming: A decline/rejection option is paired with an accept option in the same
   dialog or section, AND the decline wording uses guilt-inducing, self-deprecating, or
   emotionally loaded language compared with neutral decline wording.
3. visually_downplayed_rejection: A rejection control paired with an acceptance control is
   visually less prominent (substantially smaller area, muted/low contrast, or plain text link
   presentation vs. a filled primary button).
4. none: Normal control or non-deceptive UI element.
5. uncertain: Ambiguous or insufficient observable evidence.

Do NOT infer designer intent. Cite only observable evidence.
"""


def call_gemini_with_retry(
    model_id: str, prompt: str, control_img: Image.Image, context_img: Image.Image
) -> ControlPrediction:
    for attempt in range(1, 5):
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents=[prompt, control_img, context_img],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.0,
                    seed=42,
                    response_mime_type="application/json",
                    response_schema=ControlPrediction,
                ),
            )
            return ControlPrediction.model_validate_json(resp.text)
        except (ServerError, ClientError) as e:
            if attempt == 4:
                raise
            wait = 5 * (2 ** (attempt - 1))
            print(f"    API busy ({e.code}), retrying in {wait}s...")
            time.sleep(wait)


def extract_controls_js(page) -> list[dict]:
    return page.evaluate("""
    () => {
      const selector = 'button, a[href], input[type="checkbox"], input[type="radio"], [role="button"], [role="link"], [role="checkbox"], [role="switch"]';
      const elements = Array.from(document.querySelectorAll(selector));
      const controls = [];
      let idx = 1;

      for (const el of elements) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (rect.width < 4 || rect.height < 4 || style.display === 'none' || style.visibility === 'hidden') {
          continue;
        }
        if (rect.bottom < 0 || rect.top > window.innerHeight) continue;

        const cid = `ctrl_${String(idx++).padStart(3, '0')}`;
        el.setAttribute('data-thesis-cid', cid);

        // Programmatic label lookup
        let labelText = '';
        if (el.id) {
          const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (lbl) labelText = lbl.innerText.trim();
        }
        if (!labelText && el.closest('label')) {
          labelText = el.closest('label').innerText.trim();
        }

        // Surrounding wrapper text (captures unassociated <span> text next to inputs)
        const surroundingText = (el.parentElement ? el.parentElement.innerText : '').trim().slice(0, 200);
        const visibleText = (el.innerText || el.value || labelText || '').trim();
        const ariaLabel = el.getAttribute('aria-label') || '';
        const role = el.getAttribute('role') || el.tagName.toLowerCase();
        const checked = Boolean(el.checked || el.getAttribute('aria-checked') === 'true');

        const container = el.closest('dialog, [role="dialog"], form, section, main') || document.body;
        const siblings = Array.from(container.querySelectorAll(selector))
          .filter(s => s !== el)
          .slice(0, 6)
          .map(s => {
            const sr = s.getBoundingClientRect();
            const ss = window.getComputedStyle(s);
            return {
              text: (s.innerText || s.value || s.getAttribute('aria-label') || '').trim().slice(0, 80),
              tag: s.tagName.toLowerCase(),
              area_px: Math.round(sr.width * sr.height),
              bg_color: ss.backgroundColor,
              text_color: ss.color
            };
          });

        controls.push({
          control_id: cid,
          tag: el.tagName.toLowerCase(),
          role: role,
          visible_text: visibleText.slice(0, 150),
          accessible_name: (ariaLabel || visibleText).slice(0, 150),
          surrounding_text: surroundingText,
          checked: checked,
          font_size: style.fontSize,
          text_color: style.color,
          bg_color: style.backgroundColor,
          bbox: {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            area_px: Math.round(rect.width * rect.height)
          },
          container_bbox: (() => {
            const cr = container.getBoundingClientRect();
            return {
              x: Math.max(0, Math.round(cr.x)),
              y: Math.max(0, Math.round(cr.y)),
              width: Math.round(cr.width),
              height: Math.round(cr.height)
            };
          })(),
          siblings: siblings
        });
      }
      return controls;
    }
    """)


def map_axe_to_controls(page, violations: list[dict]) -> tuple[dict[str, list[str]], list[dict]]:
    mapped: dict[str, list[str]] = {}
    unmatched: list[dict] = []

    for v in violations:
        rule_id = v["id"]
        if rule_id not in SCOPED_AXE_RULES:
            continue
        for node in v.get("nodes", []):
            targets = node.get("target", [])
            if not targets:
                continue
            cid = page.evaluate("""
            (sel) => {
              const el = document.querySelector(sel);
              if (!el) return null;
              const direct = el.closest('[data-thesis-cid]');
              if (direct) return direct.getAttribute('data-thesis-cid');
              const lbl = el.closest('label');
              if (lbl && lbl.htmlFor) {
                const targetInput = document.getElementById(lbl.htmlFor);
                if (targetInput) return targetInput.getAttribute('data-thesis-cid');
              }
              return null;
            }
            """, targets[0])
            if cid:
                mapped.setdefault(cid, [])
                if rule_id not in mapped[cid]:
                    mapped[cid].append(rule_id)
            else:
                unmatched.append({"rule": rule_id, "target": targets[0]})
    return mapped, unmatched


def scan_target(target: str, model_id: str = "gemini-3.5-flash-lite", runs: int = 3, max_controls: int = 20):
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(target).stem if Path(target).exists() else target)[:45]
    out_dir = Path("captures") / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    url = target if target.startswith(("http://", "https://")) else Path(target).resolve().as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)

        full_shot_path = out_dir / "viewport.png"
        page.screenshot(path=str(full_shot_path), full_page=False)

        controls = extract_controls_js(page)
        axe_results = Axe().run(page)
        axe_by_cid, unmatched_axe = map_axe_to_controls(page, axe_results.response.get("violations", []))
        browser.close()

    full_img = Image.open(full_shot_path).convert("RGB")
    W, H = full_img.size
    records = []

    print(f"\nScanning '{target}' -> {len(controls)} controls found (inspecting up to {max_controls}, runs={runs})...\n")

    for ctrl in controls[:max_controls]:
        cid = ctrl["control_id"]
        b = ctrl["bbox"]
        cb = ctrl["container_bbox"]

        # 1. Control crop
        c_box = (
            max(0, b["x"] - 8),
            max(0, b["y"] - 8),
            min(W, b["x"] + b["width"] + 8),
            min(H, b["y"] + b["height"] + 8),
        )
        control_crop = full_img.crop(c_box)
        ctrl_crop_rel = f"{cid}_control.png"
        control_crop.save(out_dir / ctrl_crop_rel)

        # 2. Contextual crop with magenta bounding box
        highlighted = full_img.copy()
        draw = ImageDraw.Draw(highlighted)
        draw.rectangle(
            [b["x"] - 2, b["y"] - 2, b["x"] + b["width"] + 2, b["y"] + b["height"] + 2],
            outline="#FF00FF",
            width=3,
        )
        ctx_box = (
            max(0, cb["x"]),
            max(0, cb["y"]),
            min(W, min(cb["x"] + cb["width"], b["x"] + 650)),
            min(H, min(cb["y"] + cb["height"], b["y"] + 450)),
        )
        if ctx_box[2] - ctx_box[0] < 50 or ctx_box[3] - ctx_box[1] < 50:
            ctx_box = (max(0, b["x"] - 250), max(0, b["y"] - 200), min(W, b["x"] + 350), min(H, b["y"] + 200))
        context_crop = highlighted.crop(ctx_box)
        ctx_crop_rel = f"{cid}_context.png"
        context_crop.save(out_dir / ctx_crop_rel)

        # 3. Majority vote across `runs` deterministic VLM calls
        meta_prompt = (
            f"Evaluate control `{cid}` using Image 1 (control crop), Image 2 (magenta-highlighted context), "
            f"and structured metadata:\n{json.dumps(ctrl, indent=2)}"
        )
        run_preds = []
        for _ in range(runs):
            run_preds.append(call_gemini_with_retry(model_id, meta_prompt, control_crop, context_crop))
            time.sleep(1.5)

        labels = [p.predicted_category for p in run_preds]
        top_label, top_count = Counter(labels).most_common(1)[0]
        majority_threshold = (runs // 2) + 1
        final_dp = top_label if top_count >= majority_threshold else "uncertain"
        chosen = next((p for p in run_preds if p.predicted_category == final_dp), run_preds[0])

        # 4. Control-level resolution
        axe_hits = axe_by_cid.get(cid, [])
        has_a11y = len(axe_hits) > 0
        has_dp = final_dp not in ("none", "uncertain")

        if has_a11y and has_dp:
            outcome = "OVERLAP"
        elif has_a11y:
            outcome = "Accessibility-only"
        elif has_dp:
            outcome = "Deceptive pattern-only"
        else:
            outcome = "Normal"

        display_label = ctrl["visible_text"] or ctrl["surrounding_text"][:50] or f"<{ctrl['tag']}>"
        record = {
            "control_id": cid,
            "tag": ctrl["tag"],
            "display_label": display_label,
            "outcome": outcome,
            "axe_violations": axe_hits,
            "deceptive_pattern": final_dp,
            "run_labels": labels,
            "confidence": chosen.confidence,
            "rationale": chosen.rationale,
            "control_crop": ctrl_crop_rel,
            "context_crop": ctx_crop_rel,
            "metadata": ctrl,
        }
        records.append(record)
        print(f"  [{cid}] {outcome:22s} | axe={str(axe_hits):20s} | VLM={final_dp:28s} | {display_label[:38]}")

    summary = {
        "target": target,
        "model_id": model_id,
        "runs_per_control": runs,
        "total_controls": len(records),
        "unmatched_axe_findings": unmatched_axe,
        "controls": records,
    }
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nDone! Results saved to: {out_dir / 'results.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="URL or path to local HTML file")
    parser.add_argument("--model", default="gemini-3.5-flash-lite", help="Gemini model ID")
    parser.add_argument("--runs", type=int, default=3, help="Number of deterministic runs per control")
    parser.add_argument("--max-controls", type=int, default=20, help="Max visible controls to inspect")
    args = parser.parse_args()

    scan_target(args.target, model_id=args.model, runs=args.runs, max_controls=args.max_controls)