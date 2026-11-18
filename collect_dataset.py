import csv
import json
from pathlib import Path
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from axe_playwright_python.sync_playwright import Axe

DATASET_DIR = Path("dataset")
SCOPED_AXE_RULES = {"color-contrast", "button-name", "link-name", "label"}


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


def capture_sample(browser, sample: dict, max_controls_per_page: int = 12) -> list[dict]:
    sample_id = sample["sample_id"]
    partition = sample["partition"]
    source_type = sample["source_type"]
    target = sample["target"]

    out_dir = DATASET_DIR / partition / source_type / sample_id
    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    url = target if target.startswith(("http://", "https://")) else Path(target).resolve().as_uri()
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=35000)
        raw_html = resp.text() if resp else ""
        page.wait_for_timeout(3000 if source_type == "live" else 500)

        # Save frozen reproducibility artifacts
        (out_dir / "raw_source.html").write_text(raw_html, encoding="utf-8", errors="replace")
        (out_dir / "rendered_dom.html").write_text(page.content(), encoding="utf-8")

        viewport_path = out_dir / "viewport.png"
        page.screenshot(path=str(viewport_path), full_page=False)

        controls = extract_controls_js(page)
        axe_raw = Axe().run(page).response
        (out_dir / "axe_raw.json").write_text(json.dumps(axe_raw, indent=2), encoding="utf-8")

        axe_by_cid, unmatched_axe = map_axe_to_controls(page, axe_raw.get("violations", []))
    except Exception as e:
        print(f"  [ERROR] Failed capturing {sample_id} ({target}): {e}")
        context.close()
        return []

    context.close()

    full_img = Image.open(viewport_path).convert("RGB")
    W, H = full_img.size
    saved_controls = []
    annotation_rows = []

    for ctrl in controls[:max_controls_per_page]:
        cid = ctrl["control_id"]
        b = ctrl["bbox"]
        cb = ctrl["container_bbox"]

        # Save isolated control crop
        c_box = (
            max(0, b["x"] - 8),
            max(0, b["y"] - 8),
            min(W, b["x"] + b["width"] + 8),
            min(H, b["y"] + b["height"] + 8),
        )
        ctrl_crop_path = crops_dir / f"{cid}_control.png"
        full_img.crop(c_box).save(ctrl_crop_path)

        # Save magenta-highlighted contextual crop
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
        ctx_crop_path = crops_dir / f"{cid}_context.png"
        highlighted.crop(ctx_box).save(ctx_crop_path)

        ctrl_record = {
            **ctrl,
            "control_crop": str(ctrl_crop_path),
            "context_crop": str(ctx_crop_path),
            "axe_violations": axe_by_cid.get(cid, []),
        }
        saved_controls.append(ctrl_record)

        # Blind annotation row (NO axe_violations or VLM predictions exposed to annotators)
        annotation_rows.append(
            {
                "partition": partition,
                "source_type": source_type,
                "fixture_group": sample.get("fixture_group", sample_id),
                "sample_id": sample_id,
                "control_id": cid,
                "tag": ctrl["tag"],
                "visible_text": ctrl["visible_text"] or ctrl["surrounding_text"][:80],
                "checked": ctrl["checked"],
                "control_crop": str(ctrl_crop_path),
                "context_crop": str(ctx_crop_path),
                "annotator_1_a11y": "",
                "annotator_1_dp": "",
                "annotator_2_a11y": "",
                "annotator_2_dp": "",
                "resolved_a11y": "",
                "resolved_dp": "",
            }
        )

    bundle_meta = {
        "sample_id": sample_id,
        "partition": partition,
        "source_type": source_type,
        "fixture_group": sample.get("fixture_group", sample_id),
        "target": target,
        "total_controls_captured": len(saved_controls),
        "unmatched_axe_findings": unmatched_axe,
        "controls": saved_controls,
    }
    (out_dir / "capture_bundle.json").write_text(json.dumps(bundle_meta, indent=2), encoding="utf-8")
    print(f"  [OK] {partition:5s} | {source_type:7s} | {sample_id:32s} -> {len(saved_controls)} controls")
    return annotation_rows


def main():
    samples = []

    # 1. Load 40 generated controlled fixtures
    manifest_path = Path("fixtures/fixtures_manifest.json")
    if manifest_path.exists():
        for item in json.loads(manifest_path.read_text(encoding="utf-8")):
            samples.append(
                {
                    "sample_id": item["sample_id"],
                    "partition": item["partition"],
                    "source_type": "fixture",
                    "fixture_group": item["fixture_group"],
                    "target": item["file_path"],
                }
            )

    # 2. Load ~30 live websites from urls.txt
    urls_path = Path("urls.txt")
    if urls_path.exists():
        for line in urls_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            part, sid, url = [x.strip() for x in line.split("|", 2)]
            samples.append(
                {
                    "sample_id": sid,
                    "partition": part,
                    "source_type": "live",
                    "fixture_group": sid,
                    "target": url,
                }
            )

    print(f"Starting frozen dataset capture for {len(samples)} total pages...")
    all_annotation_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for s in samples:
            rows = capture_sample(browser, s, max_controls_per_page=12)
            all_annotation_rows.extend(rows)
        browser.close()

    if all_annotation_rows:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        csv_path = DATASET_DIR / "annotation_tasks.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_annotation_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_annotation_rows)

        pilot_count = sum(1 for r in all_annotation_rows if r["partition"] == "pilot")
        eval_count = sum(1 for r in all_annotation_rows if r["partition"] == "eval")
        print(f"\nDataset capture complete!")
        print(f"  Total captured controls : {len(all_annotation_rows)}")
        print(f"  Pilot controls (~20%)   : {pilot_count}")
        print(f"  Eval controls (~80%)    : {eval_count}")
        print(f"  Blind annotation sheet  : {csv_path}")


if __name__ == "__main__":
    main()