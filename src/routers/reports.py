import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from streamlit_utils import (
    discover_lecture_summaries,
    extract_youtube_video_id,
    trigger_airflow_dag_run,
)

router = APIRouter()

LECTURE_PIPELINE_DAG_ID = "lecture_pipeline"

class IngestRequest(BaseModel):
    video_link: str
    course_name: Optional[str] = None
    week_or_lecture: Optional[str] = None

@router.get("")
def list_reports() -> List[Dict[str, Any]]:
    output_dir = "reports"
    items = discover_lecture_summaries(output_dir)
    return [
        {
            "course": item.course,
            "lecture_number": item.lecture_number,
            "lecture_title": item.lecture_title,
            "file_path": f"reports/{item.file_path.relative_to(output_dir).as_posix()}",
            "file_name": item.file_path.name,
        }
        for item in items
    ]

@router.post("/ingest")
def ingest_video(req: IngestRequest) -> Dict[str, Any]:
    vid = extract_youtube_video_id(req.video_link)
    if not vid:
        raise HTTPException(status_code=400, detail="Invalid YouTube video link or ID.")
    
    conf = {
        "video_id": vid,
        "course_name": (req.course_name or "").strip(),
        "number_lecture": (req.week_or_lecture or "").strip(),
    }
    
    af_user = os.getenv("AIDE_AIRFLOW_USER", "airflow").strip()
    af_password = os.getenv("AIDE_AIRFLOW_PASSWORD", "airflow")
    rest_base_url = os.getenv("AIDE_AIRFLOW_REST_URL", "http://host.docker.internal:8080").rstrip("/")
    
    try:
        run = trigger_airflow_dag_run(
            dag_id=LECTURE_PIPELINE_DAG_ID,
            conf=conf,
            rest_base_url=rest_base_url,
            username=af_user,
            password=af_password,
        )
        return {"status": "ok", "dag_run": run, "video_id": vid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
