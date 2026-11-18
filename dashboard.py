import json
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Control-Level Overlap Inspector", layout="wide")
st.title("Control-Level Accessibility & Deceptive Pattern Inspector")

captures_dir = Path("captures")
result_files = sorted(captures_dir.glob("*/results.json")) if captures_dir.exists() else []

if not result_files:
    st.warning("No scan results found yet. Run `python scan_page.py fixtures/poc_fixture.html` first.")
    st.stop()

selected_file = st.sidebar.selectbox(
    "Select Captured Page",
    result_files,
    format_func=lambda p: p.parent.name,
)

data = json.loads(selected_file.read_text(encoding="utf-8"))
controls = data["controls"]
base_dir = selected_file.parent

# Summary metrics
overlaps = [c for c in controls if c["outcome"] == "OVERLAP"]
a11y_only = [c for c in controls if c["outcome"] == "Accessibility-only"]
dp_only = [c for c in controls if c["outcome"] == "Deceptive pattern-only"]
normal = [c for c in controls if c["outcome"] == "Normal"]

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Controls", len(controls))
col2.metric("Control-Level Overlaps", len(overlaps))
col3.metric("Accessibility-Only", len(a11y_only))
col4.metric("Deceptive-Only", len(dp_only))
col5.metric("Normal Controls", len(normal))

# Compare control-level overlap vs naive page-level co-occurrence baseline
total_a11y_controls = len(overlaps) + len(a11y_only)
total_dp_controls = len(overlaps) + len(dp_only)
naive_page_pairs = total_a11y_controls * total_dp_controls
st.info(
    f"**Control-Level Linkage vs. Page-Level Baseline:** Control-level resolution identified "
    f"**{len(overlaps)}** true control overlap(s), whereas a naive page-level cross-product would "
    f"pair {total_a11y_controls} accessibility finding(s) × {total_dp_controls} deceptive finding(s) = "
    f"**{naive_page_pairs}** co-occurrence pair(s)."
)

with st.expander("View Full Captured Viewport"):
    st.image(str(base_dir / "viewport.png"), use_container_width=True)

outcome_filter = st.multiselect(
    "Filter by Classification Outcome",
    ["OVERLAP", "Accessibility-only", "Deceptive pattern-only", "Normal"],
    default=["OVERLAP", "Accessibility-only", "Deceptive pattern-only", "Normal"],
)

for ctrl in controls:
    if ctrl["outcome"] not in outcome_filter:
        continue

    with st.container(border=True):
        c1, c2, c3 = st.columns([1.2, 2.0, 2.8])
        with c1:
            st.caption("Target Control Crop")
            st.image(str(base_dir / ctrl["control_crop"]))
        with c2:
            st.caption("Contextual Crop (Target Highlighted)")
            st.image(str(base_dir / ctrl["context_crop"]))
        with c3:
            st.subheader(f"{ctrl['control_id']} — {ctrl['outcome']}")
            st.markdown(f"**Control Label:** `{ctrl['display_label']}`")
            st.markdown(f"**axe-core Violations:** `{ctrl['axe_violations'] or 'None'}`")
            st.markdown(
                f"**Deceptive Pattern (3-Run Vote):** `{ctrl['deceptive_pattern']}` "
                f"(runs: `{ctrl['run_labels']}`, confidence: `{ctrl['confidence']:.2f}`)"
            )
            st.markdown(f"**Observable Rationale:** {ctrl['rationale']}")