import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

import requests


@dataclass(frozen=True)
class LectureSummary:
    course: str
    lecture_number: int | None
    lecture_title: str
    file_path: Path


_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Trailing " – (2025)" (or similar) is optional — some generated HTML omits it.
_COURSE_RE = re.compile(
    r"^(?P<course>.*?)\s*–\s*Lecture\s*(?P<num>\d+)\s*:\s*(?P<title>.*?)(?:\s*–\s*\([^)]*\))?\s*$"
)


def _extract_html_title(html_text: str) -> str | None:
    m = _TITLE_RE.search(html_text)
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title or None


def parse_summary_title(title: str, fallback_name: str) -> Tuple[str, int | None, str]:
    """
    Expected title pattern (from your generated HTML), with optional year suffix:
      '… – Lecture 3: Architectures, Hyperparameters – (2025)'
      '… – Lecture 2: Pytorch, Resource Accounting'
    """
    m = _COURSE_RE.match(title)
    if m:
        course = (m.group("course") or "").strip()
        lecture_number = int(m.group("num"))
        lecture_title = (m.group("title") or "").strip()
        return course, lecture_number, lecture_title

    # Fallback: best-effort parse from file/folder name
    course = "Summaries"
    lecture_title = title.strip() or fallback_name
    return course, None, lecture_title


def discover_lecture_summaries(output_dir: str | os.PathLike) -> List[LectureSummary]:
    base = Path(output_dir)
    if not base.exists():
        return []

    results: List[LectureSummary] = []
    for p in sorted(base.glob("*/*_lecture_summary.html")):
        try:
            html = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        title = _extract_html_title(html) or p.stem
        course, lecture_number, lecture_title = parse_summary_title(title, p.stem)
        results.append(
            LectureSummary(
                course=course,
                lecture_number=lecture_number,
                lecture_title=lecture_title,
                file_path=p,
            )
        )

    # Sort within course by lecture number (if present), else by title
    def sort_key(x: LectureSummary):
        num = x.lecture_number if x.lecture_number is not None else 10**9
        return (x.course.lower(), num, x.lecture_title.lower())

    return sorted(results, key=sort_key)


def group_by_course(items: List[LectureSummary]) -> Dict[str, List[LectureSummary]]:
    grouped: Dict[str, List[LectureSummary]] = {}
    for it in items:
        grouped.setdefault(it.course, []).append(it)
    return grouped


_YOUTUBE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
# Path-based patterns (embed, shorts, legacy watch?v= without urlparse)
_YOUTUBE_URL_RES = [
    re.compile(
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/"
        r"|youtube\.com/shorts/|m\.youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})"
    ),
    re.compile(r"[?&]v=([a-zA-Z0-9_-]{11})"),
]


def extract_youtube_video_id(url_or_id: str) -> str | None:
    """
    Return the 11-character video id only (never playlist id or other params).

    For ``youtube.com/watch?...`` URLs, only the ``v`` query parameter is used,
    so links with ``list=``, ``index=``, ``t=``, etc. still resolve to the
    correct id (e.g. ``v=25zD5qJHYsk`` → ``25zD5qJHYsk``).
    """
    text = (url_or_id or "").strip()
    if not text:
        return None
    if _YOUTUBE_ID_RE.fullmatch(text):
        return text

    parsed = urlparse(text)
    netloc = (parsed.netloc or "").lower()
    if netloc:
        if netloc.endswith("youtu.be"):
            seg = (parsed.path or "").strip("/").split("/")[0]
            if _YOUTUBE_ID_RE.fullmatch(seg):
                return seg

        if "youtube.com" in netloc:
            path = parsed.path or ""
            if path.startswith("/watch") or path in ("/watch", "/watch/", ""):
                v_list = parse_qs(parsed.query).get("v")
                if v_list:
                    v_raw = (v_list[0] or "").strip()
                    if _YOUTUBE_ID_RE.fullmatch(v_raw):
                        return v_raw

    for rx in _YOUTUBE_URL_RES:
        m = rx.search(text)
        if m:
            return m.group(1)
    return None


def trigger_airflow_dag_run(
    *,
    dag_id: str,
    conf: dict[str, Any],
    rest_base_url: str,
    username: str,
    password: str,
    unpause_first: bool = True,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """
    Create a manual DAG run via Airflow REST API v1 (basic auth).
    Unpauses the DAG first so the first trigger after deploy succeeds.
    """
    base = rest_base_url.rstrip("/")
    auth = (username, password)
    headers = {"Content-Type": "application/json"}
    if unpause_first:
        pr = requests.patch(
            f"{base}/api/v1/dags/{dag_id}",
            json={"is_paused": False},
            auth=auth,
            headers=headers,
            timeout=timeout_s,
        )
        if pr.status_code == 404:
            raise RuntimeError(f"DAG `{dag_id}` not found at {base} (HTTP 404).")
        try:
            pr.raise_for_status()
        except requests.HTTPError as e:
            raise RuntimeError(
                f"Could not unpause DAG `{dag_id}`: HTTP {pr.status_code} — {(pr.text or '')[:300]}"
            ) from e

    r = requests.post(
        f"{base}/api/v1/dags/{dag_id}/dagRuns",
        json={"conf": conf},
        auth=auth,
        headers=headers,
        timeout=timeout_s,
    )
    if not r.ok:
        try:
            body = r.json()
            detail = str(body.get("detail", body))
        except Exception:
            detail = (r.text or "")[:500]
        raise RuntimeError(f"Airflow returned {r.status_code}: {detail}")
    return r.json()

