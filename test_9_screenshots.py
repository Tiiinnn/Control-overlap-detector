import argparse
import csv
import json
import os
import re
import time
from collections import Counter
from datetime import datetime
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

load_dotenv(override=True)
api_key = os.getenv("GEMINI_API_KEY", "").strip()
if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing in .env.")

client = genai.Client(api_key=api_key)
SCOPED_AXE_RULES = {"color-contrast", "button-name", "link-name", "label"}


class ControlPrediction(BaseModel):
    visual_prominence_check: str = Field(
        description="Size, fill, contrast, and style comparison against sibling controls."
    )
    textual_tone_check: str = Field(
        description="Check for guilt-inducing, self-deprecating, or promotional marketing terms."
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
            if isinstance(e, ClientError) and e.code != 429:
                raise
            if attempt == 4:
                raise
            wait = 5 * (2 ** (attempt - 1))
            print(f"    API rate-limited/busy ({e.code}), retrying in {wait}s...")
            time.sleep(wait)


def run_rule_based_baseline(ctrl: dict) -> str:
    """
    Deterministic rule-based heuristic baseline using observable DOM/CSS/text properties:
    default checked state, marketing/shaming keywords, relative dimensions, contrast, and link styling.
    """
    tag = ctrl["tag"]
    role = ctrl["role"]
    checked = ctrl["checked"]
    text_blob = f"{ctrl['visible_text']} {ctrl['surrounding_text']}".lower().strip()
    siblings = ctrl.get("siblings", [])

    # 1. Preselected marketing consent heuristic
    marketing_terms = (
        "promo", "promotional", "marketing", "newsletter", "offers", "deals",
        "discount", "partner", "sponsor", "subscribe", "advertising", "catalog",
    )
    if (tag == "input" or role in ("checkbox", "switch")) and checked:
        if any(term in text_blob for term in marketing_terms):
            return "preselected_marketing_consent"

    # Check if paired with a primary accept control in the same container
    accept_terms = ("accept", "claim", "unlock", "agree", "subscribe", "apply", "activate", "upgrade", "keep", "add", "complete")
    primary_siblings = [
        s for s in siblings
        if any(t in s.get("text", "").lower() for t in accept_terms) and s.get("area_px", 0) > 0
    ]

    if primary_siblings and ctrl["visible_text"]:
        # 2. Confirmshaming heuristic
        shame_phrases = (
            "prefer paying", "full price", "hate ", "don't like saving", "missing out",
            "broken browsing", "staying uninformed", "throw away", "financial risk",
            "overpaying", "give up all", "enjoy waiting", "no thanks, i", "no, i ",
        )
        if any(phrase in text_blob for phrase in shame_phrases):
            return "confirmshaming"

        # 3. Visually downplayed rejection heuristic
        decline_terms = ("no", "decline", "reject", "skip", "later", "cancel", "close", "without", "guest", "standard", "dismiss")
        is_decline_text = any(term in ctrl["visible_text"].lower() for term in decline_terms)
        if is_decline_text:
            max_accept_area = max(s["area_px"] for s in primary_siblings)
            ctrl_area = ctrl["bbox"]["area_px"]
            is_plain_link = tag == "a" and ctrl["is_transparent_bg"]
            is_much_smaller = max_accept_area > 0 and (ctrl_area / max_accept_area) < 0.45
            is_low_contrast = ctrl.get("contrast_ratio", 21.0) < 4.5

            if is_plain_link or is_much_smaller or is_low_contrast:
                return "visually_downplayed_rejection"

    return "none"


def resolve_outcome(axe_hits: list[str], dp_label: str) -> str:
    has_a11y = len(axe_hits) > 0
    has_dp = dp_label not in ("none", "uncertain")
    if has_a11y and has_dp:
        return "Overlap"
    if has_a11y:
        return "Accessibility-only"
    if has_dp:
        return "Deceptive pattern-only"
    return "Normal"


def extract_controls_js(page) -> list[dict]:
    return page.evaluate("""
    () => {
      function parseRgb(str) {
        const m = str && str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
        if (!m) return null;
        return { r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1 };
      }
      function effectiveBg(el) {
        let cur = el;
        while (cur) {
          const c = parseRgb(window.getComputedStyle(cur).backgroundColor);
          if (c && c.a > 0.1) return c;
          cur = cur.parentElement;
        }
        return { r: 255, g: 255, b: 255, a: 1 };
      }
      function luminance(c) {
        const ch = [c.r, c.g, c.b].map(v => {
          v /= 255;
          return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
      }
      function contrastRatio(fg, bg) {
        const l1 = luminance(fg);
        const l2 = luminance(bg);
        return +((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2);
      }

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

        let labelText = '';
        if (el.id) {
          const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (lbl) labelText = lbl.innerText.trim();
        }
        if (!labelText && el.closest('label')) {
          labelText = el.closest('label').innerText.trim();
        }

        const surroundingText = (el.parentElement ? el.parentElement.innerText : '').trim().slice(0, 200);
        const visibleText = (el.innerText || el.value || labelText || '').trim();
        const ariaLabel = el.getAttribute('aria-label') || '';
        const role = el.getAttribute('role') || el.tagName.toLowerCase();
        const checked = Boolean(el.checked || el.getAttribute('aria-checked') === 'true');

        const fg = parseRgb(style.color) || { r: 0, g: 0, b: 0, a: 1 };
        const bg = effectiveBg(el);
        const rawBg = parseRgb(style.backgroundColor);
        const isTransparentBg = !rawBg || rawBg.a <= 0.1;

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
          is_transparent_bg: isTransparentBg,
          contrast_ratio: contrastRatio(fg, bg),
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


def map_axe_to_controls(page, violations: list[dict]) -> dict[str, list[str]]:
    mapped: dict[str, list[str]] = {}
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
    return mapped


def escape_md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def run_full_pipeline(target: str, model_id: str = "gemini-3.5-flash-lite", runs: int = 3, max_controls: int = 20):
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(target).stem if Path(target).exists() else target)[:45]
    cap_dir = Path("captures") / slug
    cap_dir.mkdir(parents=True, exist_ok=True)

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    url = target if target.startswith(("http://", "https://")) else Path(target).resolve().as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)

        full_shot_path = cap_dir / "viewport.png"
        page.screenshot(path=str(full_shot_path), full_page=False)

        controls = extract_controls_js(page)
        axe_raw = Axe().run(page).response
        axe_by_cid = map_axe_to_controls(page, axe_raw.get("violations", []))
        browser.close()

    full_img = Image.open(full_shot_path).convert("RGB")
    W, H = full_img.size

    print(f"\nPipeline Run: '{target}' | Model: '{model_id}' | Runs/Control: {runs}\n")
    print(
        f"{'Control':8s} | {'axe-core Result':18s} | {'Baseline Result':28s} | "
        f"{'Model Label':28s} | {'Conf':4s} | {'Resolved Outcome':22s} | {'Rationale'}"
    )
    print("-" * 165)

    records = []
    csv_rows = []
    md_lines = [
        f"# Control-Level Pipeline Log Table\n",
        f"- **Target:** `{target}`\n- **VLM Model:** `{model_id}` (`runs={runs}`, `temperature=0.0`, `seed=42`)\n- **Timestamp:** `{timestamp}`\n",
        "| Control ID | Control Text / Tag | `axe-core` Result | Rule-Based Baseline | Model Label (Majority Vote) | Confidence | Rationale | Resolved Outcome (VLM + axe) | Resolved Outcome (Baseline + axe) |",
        "| :--- | :--- | :--- | :--- | :--- | :---: | :--- | :--- | :--- |",
    ]

    for ctrl in controls[:max_controls]:
        cid = ctrl["control_id"]
        b = ctrl["bbox"]
        cb = ctrl["container_bbox"]

        # 1. Crops
        c_box = (max(0, b["x"] - 8), max(0, b["y"] - 8), min(W, b["x"] + b["width"] + 8), min(H, b["y"] + b["height"] + 8))
        control_crop = full_img.crop(c_box)
        control_crop.save(cap_dir / f"{cid}_control.png")

        highlighted = full_img.copy()
        draw = ImageDraw.Draw(highlighted)
        draw.rectangle([b["x"] - 2, b["y"] - 2, b["x"] + b["width"] + 2, b["y"] + b["height"] + 2], outline="#FF00FF", width=3)
        ctx_box = (max(0, cb["x"]), max(0, cb["y"]), min(W, min(cb["x"] + cb["width"], b["x"] + 650)), min(H, min(cb["y"] + cb["height"], b["y"] + 450)))
        if ctx_box[2] - ctx_box[0] < 50 or ctx_box[3] - ctx_box[1] < 50:
            ctx_box = (max(0, b["x"] - 250), max(0, b["y"] - 200), min(W, b["x"] + 350), min(H, b["y"] + 200))
        context_crop = highlighted.crop(ctx_box)
        context_crop.save(cap_dir / f"{cid}_context.png")

        # 2. Branch A: axe-core result
        axe_hits = axe_by_cid.get(cid, [])
        axe_str = ", ".join(axe_hits) if axe_hits else "none"

        # 3. Branch B: Rule-based heuristic baseline result
        baseline_label = run_rule_based_baseline(ctrl)

        # 4. Branch C: Multimodal VLM detector (3-run majority vote)
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
        majority_needed = (runs // 2) + 1
        model_label = top_label if top_count >= majority_needed else "uncertain"
        chosen = next((p for p in run_preds if p.predicted_category == model_label), run_preds[0])

        # 5. Control-level resolved outcomes
        resolved_vlm = resolve_outcome(axe_hits, model_label)
        resolved_baseline = resolve_outcome(axe_hits, baseline_label)

        display_text = ctrl["visible_text"] or ctrl["surrounding_text"][:55] or f"<{ctrl['tag']}>"

        print(
            f"{cid:8s} | {axe_str:18s} | {baseline_label:28s} | "
            f"{model_label:28s} | {chosen.confidence:4.2f} | {resolved_vlm:22s} | {chosen.rationale}"
        )

        record = {
            "control_id": cid,
            "control_text": display_text,
            "axe_core_result": axe_hits,
            "baseline_result": baseline_label,
            "model_label": model_label,
            "run_votes": labels,
            "confidence": chosen.confidence,
            "rationale": chosen.rationale,
            "resolved_outcome_vlm": resolved_vlm,
            "resolved_outcome_baseline": resolved_baseline,
        }
        records.append(record)

        csv_rows.append(
            {
                "control_id": cid,
                "control_text": display_text,
                "axe_core_result": axe_str,
                "baseline_result": baseline_label,
                "model_label": model_label,
                "run_votes": " / ".join(labels),
                "confidence": f"{chosen.confidence:.2f}",
                "rationale": chosen.rationale,
                "resolved_outcome_vlm": resolved_vlm,
                "resolved_outcome_baseline": resolved_baseline,
            }
        )

        md_lines.append(
            f"| `{cid}` "
            f"| {escape_md(display_text)} "
            f"| `{escape_md(axe_str)}` "
            f"| `{escape_md(baseline_label)}` "
            f"| **{escape_md(model_label)}** ({top_count}/{runs}) "
            f"| {chosen.confidence:.2f} "
            f"| {escape_md(chosen.rationale)} "
            f"| **{resolved_vlm}** "
            f"| {resolved_baseline} |"
        )

    # Save permanent log files (both timestamped archive and 'latest' shortcut)
    for prefix in (f"{slug}_{timestamp}", "latest"):
        (logs_dir / f"{prefix}_results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        (logs_dir / f"{prefix}_log_table.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        with (logs_dir / f"{prefix}_log_table.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)

    print("-" * 165)
    print(f"Permanent log tables saved to '{logs_dir}/':")
    print(f"  - {logs_dir / f'{slug}_{timestamp}_log_table.md'}")
    print(f"  - {logs_dir / f'{slug}_{timestamp}_log_table.csv'}")
    print(f"  - {logs_dir / f'{slug}_{timestamp}_results.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="URL or local HTML fixture path")
    parser.add_argument("--model", default="gemini-3.5-flash-lite", help="Gemini model ID")
    parser.add_argument("--runs", type=int, default=3, help="Runs per control (default: 3)")
    parser.add_argument("--max-controls", type=int, default=20, help="Max controls to inspect")
    args = parser.parse_args()

    run_full_pipeline(args.target, model_id=args.model, runs=args.runs, max_controls=args.max_controls)