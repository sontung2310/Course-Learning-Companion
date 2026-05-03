from __future__ import annotations

import os
import re
from pathlib import Path
import base64

import streamlit as st
import streamlit.components.v1 as components

from streamlit_utils import (
    discover_lecture_summaries,
    extract_youtube_video_id,
    group_by_course,
    trigger_airflow_dag_run,
)


st.set_page_config(page_title="Summaries", page_icon="📚", layout="wide")

LECTURE_PIPELINE_DAG_ID = "lecture_pipeline"


def _airflow_rest_base_default() -> str:
    return os.getenv("AIDE_AIRFLOW_REST_URL", "http://localhost:8080").rstrip("/")


def _get_airflow_rest_base() -> str:
    if "airflow_rest_base_url" not in st.session_state:
        st.session_state.airflow_rest_base_url = _airflow_rest_base_default()
    return st.session_state.airflow_rest_base_url


def _set_airflow_rest_base(value: str) -> None:
    st.session_state.airflow_rest_base_url = value.rstrip("/")


if not st.session_state.get("user_profile"):
    st.error("You must log in first on the **Course Learning Assistant** home page.")
    st.stop()

st.title("Summarized documents")

st.subheader("Ingest a preferred lecture video")
st.caption(
    "Triggers the Airflow DAG `lecture_pipeline` (transcript → refined HTML report → ChromaDB). "
    "Ensure the Airflow stack is running and reachable from this machine."
)
with st.form("ingest_lecture_form"):
    col_a, col_b = st.columns(2)
    with col_a:
        video_link = st.text_input(
            "Video link or YouTube ID",
            placeholder="https://www.youtube.com/watch?v=… or dQw4w9WgXcQ",
            help="Full YouTube URL (watch, youtu.be, shorts, embed) or the 11-character video id.",
        )
        course_name = st.text_input(
            "Course name (optional)",
            placeholder="e.g. Stanford CS336",
        )
    with col_b:
        week_or_lecture = st.text_input(
            "Week / lecture label (optional)",
            placeholder='e.g. Week 3 or "Lecture 5: GPUs"',
            help="Passed to the pipeline as the lecture line in the transcript step.",
        )
    submitted = st.form_submit_button("Run ingestion pipeline")

if submitted:
    # Keep Airflow connection details out of the UI.
    # Configure via env vars:
    # - AIDE_AIRFLOW_REST_URL (default http://localhost:8080)
    # - AIDE_AIRFLOW_USER / AIDE_AIRFLOW_PASSWORD (default airflow/airflow)
    _get_airflow_rest_base()
    vid = extract_youtube_video_id(video_link)
    if not vid:
        st.error(
            "Could not parse a YouTube video id from that input. "
            "Paste a full watch URL, youtu.be link, or the 11-character id."
        )
    else:
        conf = {
            "video_id": vid,
            "course_name": (course_name or "").strip(),
            "number_lecture": (week_or_lecture or "").strip(),
        }
        af_user = os.getenv("AIDE_AIRFLOW_USER", "airflow").strip()
        af_password = os.getenv("AIDE_AIRFLOW_PASSWORD", "airflow")
        try:
            run = trigger_airflow_dag_run(
                dag_id=LECTURE_PIPELINE_DAG_ID,
                conf=conf,
                rest_base_url=_get_airflow_rest_base(),
                username=af_user,
                password=af_password,
            )
            run_id = run.get("dag_run_id") or run.get("run_id") or "?"
            base_ui = _get_airflow_rest_base()
            st.success(
                f"Started DAG run `{run_id}` for video `{vid}`. "
                f"When it completes, refresh this page and open the new summary under `reports/{vid}/`."
            )
            st.markdown(
                f"[Open Airflow UI — DAG runs]({base_ui}/dags/{LECTURE_PIPELINE_DAG_ID}/grid)"
            )
        except RuntimeError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Request failed: `{e}`")

st.divider()

output_dir = Path(st.text_input("Output directory", value="reports")).resolve()

items = discover_lecture_summaries(output_dir)
if not items:
    st.info(
        "No lecture summary HTML files found yet under "
        f"`{output_dir}` (expected `…/*/*_lecture_summary.html`). "
        "Run ingestion above, wait for the pipeline to finish, then refresh."
    )
else:
    grouped = group_by_course(items)

    st.subheader("Index")
    for course, lectures in grouped.items():
        st.markdown(f"**{course}**")
        for lec in lectures:
            label = (
                f"Lecture {lec.lecture_number}: {lec.lecture_title}"
                if lec.lecture_number is not None
                else lec.lecture_title
            )
            cols = st.columns([6, 1, 1])
            cols[0].write(label)
            if cols[1].button("View", key=f"view:{lec.file_path}"):
                st.session_state.selected_summary_path = str(lec.file_path)
            with cols[2]:
                try:
                    cols[2].download_button(
                        "Download",
                        data=lec.file_path.read_bytes(),
                        file_name=lec.file_path.name,
                        mime="text/html",
                        key=f"dl:{lec.file_path}",
                    )
                except Exception:
                    cols[2].write("")

st.divider()

selected = st.session_state.get("selected_summary_path")
if selected:
    p = Path(selected)
    if not p.is_file():
        st.warning(f"Previously selected file is missing: `{p}`. Choose another from the index.")
        st.session_state.pop("selected_summary_path", None)
    else:
        st.subheader(f"Preview: `{p.name}`")
        try:
            html = p.read_text(encoding="utf-8", errors="ignore")

            # The original HTML uses relative image paths like src="frames/xxx.jpg",
            # which do not resolve inside Streamlit. Rewrite them to inline
            # base64 data URLs so images render correctly in the browser.
            def _replace_img(match: re.Match[str]) -> str:
                src = match.group("src")
                alt = match.group("alt") or ""
                img_path = (p.parent / src).resolve()
                if not img_path.exists():
                    # Keep the original tag if image is missing
                    return match.group(0)
                try:
                    data = img_path.read_bytes()
                    b64 = base64.b64encode(data).decode("ascii")
                    # Naively assume JPEG; your pipeline uses .jpg files.
                    return f'<img src="data:image/jpeg;base64,{b64}" alt="{alt}">'
                except Exception:
                    return match.group(0)

            img_pattern = re.compile(
                r'<img\s+src="(?P<src>[^"]+)"\s+alt="(?P<alt>[^"]*)"\s*/?>',
                re.IGNORECASE,
            )
            html_with_images = img_pattern.sub(_replace_img, html)

            components.html(html_with_images, height=900, scrolling=True)
        except Exception as e:
            st.error(f"Failed to read HTML: {e}")
elif items:
    st.caption("Click **View** to preview a summary here.")
