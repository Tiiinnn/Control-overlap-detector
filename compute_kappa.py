from pathlib import Path
import pandas as pd
from sklearn.metrics import cohen_kappa_score

ANN_DIR = Path("dataset/annotations")


def binary_presence(series: pd.Series, target_token: str) -> list[int]:
    return [1 if target_token in str(val).split("+") else 0 for val in series]


def evaluate_pair(pair_name: str, file_1: Path, file_2: Path) -> pd.DataFrame:
    df1 = pd.read_csv(file_1, keep_default_na=False)
    df2 = pd.read_csv(file_2, keep_default_na=False)

    merged = pd.merge(
        df1,
        df2,
        on=["pair", "partition", "source_type", "fixture_group", "sample_id", "control_id", "tag", "visible_text", "checked", "control_crop", "context_crop"],
        suffixes=("_1", "_2"),
    )

    incomplete = merged[
        (merged["a11y_label_1"] == "")
        | (merged["a11y_label_2"] == "")
        | (merged["dp_label_1"] == "")
        | (merged["dp_label_2"] == "")
    ]
    if len(incomplete) > 0:
        print(f"  [WARNING] {pair_name} still has {len(incomplete)} unlabeled control(s).")
        merged = merged.drop(incomplete.index)

    if len(merged) == 0:
        return merged

    k_a11y = cohen_kappa_score(merged["a11y_label_1"], merged["a11y_label_2"])
    k_dp = cohen_kappa_score(merged["dp_label_1"], merged["dp_label_2"])

    print(f"\n=== {pair_name.upper()} Inter-Annotator Agreement (N = {len(merged)} controls) ===")
    print(f"  Annotator 1: {df1['annotator_name'].iloc[0]}")
    print(f"  Annotator 2: {df2['annotator_name'].iloc[0]}")
    print(f"  Overall Accessibility Exact-Match Kappa    : {k_a11y:.4f}")
    print(f"  Overall Deceptive-Pattern Exact-Match Kappa: {k_dp:.4f}")

    for rule in ["color-contrast", "button-name", "link-name", "label"]:
        k_bin = cohen_kappa_score(
            binary_presence(merged["a11y_label_1"], rule),
            binary_presence(merged["a11y_label_2"], rule),
        )
        print(f"    - A11y [{rule:15s}] binary kappa: {k_bin:.4f}")

    for pat in ["preselected_marketing_consent", "confirmshaming", "visually_downplayed_rejection"]:
        k_bin = cohen_kappa_score(
            binary_presence(merged["dp_label_1"], pat),
            binary_presence(merged["dp_label_2"], pat),
        )
        print(f"    - DP   [{pat:30s}] binary kappa: {k_bin:.4f}")

    return merged


def main():
    pairs = [
        ("pair_a", ANN_DIR / "pair_a_annotator_1.csv", ANN_DIR / "pair_a_annotator_2.csv"),
        ("pair_b", ANN_DIR / "pair_b_annotator_1.csv", ANN_DIR / "pair_b_annotator_2.csv"),
    ]

    all_merged = []
    for name, f1, f2 in pairs:
        if f1.exists() and f2.exists():
            m = evaluate_pair(name, f1, f2)
            if len(m) > 0:
                all_merged.append(m)

    if not all_merged:
        print("No completed pair annotations available yet.")
        return

    full_df = pd.concat(all_merged, ignore_index=True)

    # Combined pre-resolution kappa across all annotated controls
    print(f"\n=== COMBINED PRE-RESOLUTION KAPPA (N = {len(full_df)} controls) ===")
    print(f"  Combined Accessibility Kappa    : {cohen_kappa_score(full_df['a11y_label_1'], full_df['a11y_label_2']):.4f}")
    print(f"  Combined Deceptive-Pattern Kappa: {cohen_kappa_score(full_df['dp_label_1'], full_df['dp_label_2']):.4f}")

    # Pre-fill resolved columns where both annotators agreed; leave blank where they disagreed
    agree_a11y = full_df["a11y_label_1"] == full_df["a11y_label_2"]
    agree_dp = full_df["dp_label_1"] == full_df["dp_label_2"]

    full_df["resolved_a11y"] = full_df["a11y_label_1"].where(agree_a11y, "")
    full_df["resolved_dp"] = full_df["dp_label_1"].where(agree_dp, "")
    full_df["resolution_source"] = "pair_agreement"
    full_df.loc[~(agree_a11y & agree_dp), "resolution_source"] = "NEEDS_REVIEW"

    disagreements = full_df[~(agree_a11y & agree_dp)]
    disagreements.to_csv(ANN_DIR / "disagreements_to_resolve.csv", index=False)
    full_df.to_csv(ANN_DIR / "ground_truth.csv", index=False)

    print(f"\nDisagreements requiring review: {len(disagreements)} / {len(full_df)}")
    print(f"  Review file saved to : {ANN_DIR / 'disagreements_to_resolve.csv'}")
    print(f"  Master ground truth  : {ANN_DIR / 'ground_truth.csv'}")


if __name__ == "__main__":
    main()