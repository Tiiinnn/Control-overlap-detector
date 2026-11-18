import csv
from pathlib import Path

TASKS_CSV = Path("dataset/annotation_tasks.csv")
OUT_DIR = Path("dataset/annotations")

PAIR_ASSIGNMENTS = {
    "pair_a": ("Justin Miguel G. Antenor", "Michaella P. Balagtas"),
    "pair_b": ("Brylle Julian D. Fajutnao", "David Kalel D. Sta. Teresa"),
}


def main():
    if not TASKS_CSV.exists():
        raise FileNotFoundError(f"Missing {TASKS_CSV}. Run collect_dataset.py first.")

    with TASKS_CSV.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Group by sample_id so an entire page stays within one annotator pair
    unique_samples = sorted({r["sample_id"] for r in rows})
    pair_a_samples = set(unique_samples[::2])
    pair_b_samples = set(unique_samples[1::2])

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    base_fields = [
        "pair",
        "annotator_name",
        "partition",
        "source_type",
        "fixture_group",
        "sample_id",
        "control_id",
        "tag",
        "visible_text",
        "checked",
        "control_crop",
        "context_crop",
        "a11y_label",
        "dp_label",
        "notes",
    ]

    splits = [
        ("pair_a", PAIR_ASSIGNMENTS["pair_a"][0], pair_a_samples, OUT_DIR / "pair_a_annotator_1.csv"),
        ("pair_a", PAIR_ASSIGNMENTS["pair_a"][1], pair_a_samples, OUT_DIR / "pair_a_annotator_2.csv"),
        ("pair_b", PAIR_ASSIGNMENTS["pair_b"][0], pair_b_samples, OUT_DIR / "pair_b_annotator_1.csv"),
        ("pair_b", PAIR_ASSIGNMENTS["pair_b"][1], pair_b_samples, OUT_DIR / "pair_b_annotator_2.csv"),
    ]

    for pair_id, annotator, allowed_samples, out_path in splits:
        subset = []
        for r in rows:
            if r["sample_id"] not in allowed_samples:
                continue
            subset.append(
                {
                    "pair": pair_id,
                    "annotator_name": annotator,
                    "partition": r["partition"],
                    "source_type": r["source_type"],
                    "fixture_group": r["fixture_group"],
                    "sample_id": r["sample_id"],
                    "control_id": r["control_id"],
                    "tag": r["tag"],
                    "visible_text": r["visible_text"],
                    "checked": r["checked"],
                    "control_crop": r["control_crop"],
                    "context_crop": r["context_crop"],
                    "a11y_label": "",
                    "dp_label": "",
                    "notes": "",
                }
            )

        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=base_fields)
            writer.writeheader()
            writer.writerows(subset)

        print(f"Created {out_path} ({len(subset)} controls) -> {annotator}")


if __name__ == "__main__":
    main()