"""Renders report_build.py's ReportData into HTML (preview) or PDF bytes
(the stored report), via one shared Jinja2 template + WeasyPrint -- one
styling system for both preview and the final document, and WeasyPrint's
CSS Paged Media support (@page, running headers/footers, page counters)
handles a multi-page accounting document far better than hand-positioned
drawing calls would. @page rules are ignored by a plain browser (harmless
for the HTML preview) and honored by WeasyPrint (the actual PDF).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from .report_build import ReportData

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html"]),
)
_template = _env.get_template("report_pdf.html")


@dataclass
class ReportMeta:
    report_id: str  # a real id once persisted, or "Vorschau" for a preview -- used for the PDF
    # filename/URL only, deliberately not shown in the document itself (see report_pdf.html):
    # the user-given `title` below is what identifies a report to a human.
    title: str
    generated_at: datetime
    period_from: str | None
    period_to: str | None
    source_names: list[str]
    vehicle_names: list[str]
    show_signature_line: bool = False
    orientation: str = "portrait"


def render_html(data: ReportData, meta: ReportMeta) -> str:
    return _template.render(data=data, meta=meta)


def render_pdf(data: ReportData, meta: ReportMeta) -> bytes:
    return HTML(string=render_html(data, meta)).write_pdf()
