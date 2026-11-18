from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Blind Control Annotator", layout="wide")
st.title("Stage 3: Blind Control Annotation Tool")

ann_dir = Path("dataset/annotations")
csv_files = sorted(ann_dir.glob("pair_*_annotator_*.csv")) if ann_dir.exists() else []

if not csv_files:
    st.error("No annotator CSVs found. Run `python prepare_annotation.py` first.")
    st.stop()

selected_csv = st.sidebar.selectbox(
    "Select Your Annotator File",
    csv_files,
    format_func=lambda p: p.name,
)

df = pd.read_csv(selected_csv, keep_default_na=False)
total = len(df)
completed = int(((df["a11y_label"] != "") & (df["dp_label"] != "")).sum())

st.sidebar.metric("Progress", f"{completed} / {total} controls")
show_unlabeled_only = st.sidebar.checkbox("Jump to unlabeled controls only", value=True)

candidate_indices = (
    df.index[(df["a11y_label"] == "") | (df["dp_label"] == "")].tolist()
    if show_unlabeled_only
    else df.index.tolist()
)

if not candidate_indices:
    st.success(f"All {total} controls in `{selected_csv.name}` are labeled! You are ready for Cohen's kappa calculation.")
    st.stop()

idx = st.sidebar.selectbox(
    "Control Index",
    candidate_indices,
    format_func=lambda i: f"#{i + 1}: {df.loc[i, 'sample_id']} / {df.loc[i, 'control_id']}",
)

row = df.loc[idx]
st.subheader(f"{row['sample_id']} — `{row['control_id']}` ({row['partition'].upper()})")
st.caption(f"Annotator: **{row['annotator_name']}** | Tag: `<{row['tag']}>` | Checked at load: `{row['checked']}`")

col_img1, col_img2, col_form = st.columns([1.1, 1.9, 2.0])

with col_img1:
    st.markdown("**1. Isolated Control Crop**")
    if Path(row["control_crop"]).exists():
        st.image(row["control_crop"])

with col_img2:
    st.markdown("**2. Contextual Crop (Target in Magenta)**")
    if Path(row["context_crop"]).exists():
        st.image(row["context_crop"])
    st.markdown(f"**Visible / Adjacent Text:** `{row['visible_text']}`")

with col_form:
    st.markdown("**3. Assign Independent Labels**")

    existing_a11y = [x for x in row["a11y_label"].split("+") if x and x != "none"]
    a11y_choices = st.multiselect(
        "Accessibility Violations (leave empty if compliant)",
        ["color-contrast", "button-name", "link-name", "label"],
        default=existing_a11y,
    )

    existing_dp = [x for x in row["dp_label"].split("+") if x and x != "none"]
    dp_choices = st.multiselect(
        "Potential Deceptive Patterns (leave empty if normal)",
        [
            "preselected_marketing_consent",
            "confirmshaming",
            "visually_downplayed_rejection",
            "uncertain",
        ],
        default=existing_dp,
    )

    notes = st.text_input("Optional Objective Note", value=row["notes"])

    if st.button("Save Annotation", type="primary"):
        df.loc[idx, "a11y_label"] = "+".join(sorted(a11y_choices)) if a11y_choices else "none"
        df.loc[idx, "dp_label"] = "+".join(sorted(dp_choices)) if dp_choices else "none"
        df.loc[idx, "notes"] = notes
        df.to_csv(selected_csv, index=False)
        st.rerun()