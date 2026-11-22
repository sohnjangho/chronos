"""보고서 내보내기(독립 HTML/인쇄용 PDF 및 OpenXML .docx 생성)."""

import io
import re
import zipfile
from html import escape
from xml.sax.saxutils import escape as xml_escape

from app.store.tables import ReportRow

CADENCE_LABEL = {"monthly": "월간", "quarterly": "분기별"}


def _fmt_num(v: object) -> str:
    return "" if v is None else str(v)


def _render_svg_chart(chart: dict) -> str:
    kind = chart.get("kind")
    points = chart.get("points") or []
    if not points:
        return '<p class="muted">표시할 시계열 데이터가 없습니다.</p>'
    w, h, left, right, top, bottom = 640, 220, 44, 24, 16, 28
    iw, ih = w - left - right, h - top - bottom

    if kind == "spi_trend":
        vals = [float(p["spi"]) for p in points]
        lo = max(0.0, min(0.8, min(vals) - 0.05))
        hi = max(1.15, max(vals) + 0.05)

        def sx(i: int) -> float:
            return left + (iw / 2 if len(points) == 1 else (i / (len(points) - 1)) * iw)

        def sy(v: float) -> float:
            return top + ((hi - v) / max(hi - lo, 0.01)) * ih

        d = " ".join(f"{'M' if i == 0 else 'L'}{sx(i):.1f} {sy(float(p['spi'])):.1f}" for i, p in enumerate(points))
        y1 = sy(1.0)
        y09 = sy(0.9)
        dots = "".join(f'<circle cx="{sx(i):.1f}" cy="{sy(float(p["spi"])):.1f}" r="3.5" fill="#2f6fdb" />' for i, p in enumerate(points))
        first_d = escape(str(points[0]["date"]))
        last_d = escape(str(points[-1]["date"]))
        return (
            f'<svg width="100%" viewBox="0 0 {w} {h}" role="img" aria-label="SPI 추이 차트">'
            f'<rect x="{left}" y="{y09:.1f}" width="{iw}" height="{max(0.0, top + ih - y09):.1f}" fill="#fbe0e0" fill-opacity="0.55" />'
            f'<line x1="{left}" x2="{w - right}" y1="{y1:.1f}" y2="{y1:.1f}" stroke="#566175" stroke-dasharray="4 4" />'
            f'<line x1="{left}" x2="{w - right}" y1="{y09:.1f}" y2="{y09:.1f}" stroke="#c93b3b" stroke-dasharray="2 3" />'
            f'<text x="{left - 6}" y="{y1 + 4:.1f}" text-anchor="end" font-size="11" fill="#566175">1.00</text>'
            f'<text x="{left - 6}" y="{y09 + 4:.1f}" text-anchor="end" font-size="11" fill="#c93b3b">0.90</text>'
            f'<path d="{d}" fill="none" stroke="#2f6fdb" stroke-width="2.5" />'
            f"{dots}"
            f'<text x="{left}" y="{h - 6}" font-size="11" fill="#566175">{first_d}</text>'
            f'<text x="{w - right}" y="{h - 6}" text-anchor="end" font-size="11" fill="#566175">{last_d}</text>'
            "</svg>"
        )

    def sx(i: int) -> float:
        return left + (iw / 2 if len(points) == 1 else (i / (len(points) - 1)) * iw)

    def sy(pct_val: float) -> float:
        return top + ((100.0 - max(0.0, min(100.0, pct_val))) / 100.0) * ih

    plan_d = " ".join(f"{'M' if i == 0 else 'L'}{sx(i):.1f} {sy(float(p['plan_cum'])):.1f}" for i, p in enumerate(points))
    act_pts = [(i, float(p["actual_cum"])) for i, p in enumerate(points) if p.get("actual_cum") is not None]
    act_d = " ".join(f"{'M' if j == 0 else 'L'}{sx(i):.1f} {sy(v):.1f}" for j, (i, v) in enumerate(act_pts))
    fc_pts = [(i, float(p["forecast_cum"])) for i, p in enumerate(points) if p.get("forecast_cum") is not None]
    fc_d = " ".join(f"{'M' if j == 0 else 'L'}{sx(i):.1f} {sy(v):.1f}" for j, (i, v) in enumerate(fc_pts))
    grid = "".join(
        f'<line x1="{left}" x2="{w - right}" y1="{sy(p):.1f}" y2="{sy(p):.1f}" stroke="#d9dfe8" />'
        f'<text x="{left - 6}" y="{sy(p) + 4:.1f}" text-anchor="end" font-size="11" fill="#566175">{p}%</text>'
        for p in (0, 25, 50, 75, 100)
    )
    first_d = escape(str(points[0]["date"]))
    last_d = escape(str(points[-1]["date"]))
    return (
        f'<svg width="100%" viewBox="0 0 {w} {h}" role="img" aria-label="월간 공정률 S-커브">'
        f"{grid}"
        f'<path d="{plan_d}" fill="none" stroke="#566175" stroke-width="2" />'
        + (f'<path d="{fc_d}" fill="none" stroke="#c93b3b" stroke-width="2" stroke-dasharray="5 4" />' if fc_d else "")
        + (f'<path d="{act_d}" fill="none" stroke="#1f9d55" stroke-width="3" />' if act_d else "")
        + f'<text x="{left}" y="{h - 6}" font-size="11" fill="#566175">{first_d}</text>'
        + f'<text x="{w - right}" y="{h - 6}" text-anchor="end" font-size="11" fill="#566175">{last_d}</text>'
        + '<text x="' + str(w - right) + '" y="14" text-anchor="end" font-size="11" fill="#182132">계획(회색) · 실적(초록) · 예측(점선)</text>'
        + "</svg>"
    )


def render_html(report: ReportRow, project_name: str) -> str:
    """브라우저 미리보기 · PDF 인쇄용 독립 HTML 문자열."""
    parts: list[str] = []
    for blk in report.blocks_json:
        parts.append(f"<h2>{escape(str(blk.get('heading', '')))}</h2>")
        kind = blk.get("block_kind")
        if kind == "kpi":
            cards = "".join(
                f'<div class="kpi"><div class="kpi-l">{escape(str(m.get("label", "")))}</div>'
                f'<div class="kpi-v">{escape(str(m.get("value", "")))}</div>'
                f'<div class="kpi-s">{escape(str(m.get("sub", "")))}</div></div>'
                for m in (blk.get("metrics") or [])
            )
            parts.append(f'<div class="kpi-grid">{cards}</div>')
        elif kind == "table":
            tbl = blk.get("table") or {}
            cols = tbl.get("columns") or []
            rows = tbl.get("rows") or []
            if rows:
                ths = "".join(f"<th>{escape(str(c))}</th>" for c in cols)
                trs = "".join("<tr>" + "".join(f"<td>{escape(_fmt_num(cell))}</td>" for cell in row) + "</tr>" for row in rows)
                parts.append(f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>")
            else:
                parts.append(f'<p class="muted">{escape(str(blk.get("text") or "해당 자료가 없습니다."))}</p>')
        elif kind == "chart":
            parts.append(_render_svg_chart(blk.get("chart") or {}))
            if blk.get("text"):
                parts.append(f'<p class="caption">{escape(str(blk["text"]))}</p>')
        else:
            raw_text = str(blk.get("text") or "").strip() or "(내용 없음)"
            for line in raw_text.splitlines():
                parts.append(f"<p>{escape(line)}</p>" if line.strip() else "<br />")

    cadence_kr = CADENCE_LABEL.get(report.cadence, report.cadence)
    body_html = "\n".join(parts)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<title>{escape(report.title)}</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  body {{ margin: 0; font-family: "Noto Sans KR", "Apple SD Gothic Neo", sans-serif; color: #182132; background: #fff; font-size: 12px; line-height: 1.6; }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 20px 24px; }}
  .head {{ border-bottom: 2px solid #1b2845; padding-bottom: 10px; margin-bottom: 14px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #e3edfb; color: #1f4f9e; font-size: 11px; font-weight: 700; margin-right: 6px; }}
  h1 {{ margin: 6px 0 4px; font-size: 20px; color: #182132; }}
  .meta {{ font-size: 11px; color: #566175; }}
  h2 {{ margin: 18px 0 8px; font-size: 14px; padding-bottom: 4px; border-bottom: 1px solid #d9dfe8; page-break-after: avoid; }}
  p {{ margin: 4px 0; }}
  .muted {{ color: #566175; }}
  .caption {{ font-size: 11px; color: #566175; margin-top: 4px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 6px 0 10px; }}
  .kpi {{ border: 1px solid #d9dfe8; border-radius: 6px; padding: 8px 10px; background: #f7f9fc; }}
  .kpi-l {{ font-size: 11px; color: #566175; }}
  .kpi-v {{ font-size: 16px; font-weight: 700; margin: 2px 0; }}
  .kpi-s {{ font-size: 11px; color: #566175; }}
  table {{ border-collapse: collapse; width: 100%; margin: 6px 0 10px; page-break-inside: avoid; }}
  th, td {{ border: 1px solid #cfd6e0; padding: 5px 8px; text-align: left; font-size: 11px; }}
  th {{ background: #f3f5f8; font-weight: 700; }}
  @media print {{ .no-print {{ display: none; }} .wrap {{ padding: 0; max-width: none; }} }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div><span class="badge">{escape(cadence_kr)} 보고서</span><span class="meta">적용 양식: {escape(report.template_name)}</span></div>
    <h1>{escape(report.title)}</h1>
    <div class="meta">프로젝트: {escape(project_name)} · 기간: {escape(report.period_label)} · 기준일(Data Date): {escape(report.data_date)} · 버전 v{report.schedule_version} · 작성 {escape(report.created_by)}</div>
  </div>
  {body_html}
</div>
</body>
</html>"""


def _safe_xml(val: object) -> str:
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", _fmt_num(val))
    return xml_escape(clean)


def _w_p(text: str, *, bold: bool = False, size_half_pt: int = 21, color: str = "182132", spacing_after: int = 80) -> str:
    rpr = f'<w:rPr><w:sz w:val="{size_half_pt}"/><w:szCs w:val="{size_half_pt}"/><w:color w:val="{color}"/>'
    if bold:
        rpr += "<w:b/>"
    rpr += "</w:rPr>"
    return f'<w:p><w:pPr><w:spacing w:after="{spacing_after}"/></w:pPr><w:r>{rpr}<w:t xml:space="preserve">{_safe_xml(text)}</w:t></w:r></w:p>'


def _w_table(cols: list[str], rows: list[list[object]]) -> str:
    def cell(text: object, header: bool = False) -> str:
        fill = '<w:shd w:val="clear" w:color="auto" w:fill="F3F5F8"/>' if header else ""
        return (
            f"<w:tc><w:tcPr>{fill}"
            '<w:tcMar><w:top w:w="70" w:type="dxa"/><w:bottom w:w="70" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tcMar>'
            f"</w:tcPr>{_w_p(_fmt_num(text), bold=header, size_half_pt=19, spacing_after=0)}</w:tc>"
        )

    header_row = "<w:tr>" + "".join(cell(c, header=True) for c in cols) + "</w:tr>"
    body_rows = "".join("<w:tr>" + "".join(cell(v) for v in row) + "</w:tr>" for row in rows)
    borders = (
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="CFD6E0"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="CFD6E0"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="CFD6E0"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="CFD6E0"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="CFD6E0"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="CFD6E0"/>'
        "</w:tblBorders>"
    )
    return f'<w:tbl><w:tblPr><w:tblW w:w="9600" w:type="dxa"/>{borders}</w:tblPr>{header_row}{body_rows}</w:tbl>'


def render_docx(report: ReportRow, project_name: str) -> bytes:
    """표준 OpenXML Word(.docx) 문서 바이트 생성."""
    cadence_kr = CADENCE_LABEL.get(report.cadence, report.cadence)
    body: list[str] = [
        _w_p(report.title, bold=True, size_half_pt=34, color="1B2845", spacing_after=60),
        _w_p(
            f"[{cadence_kr} 보고서] 프로젝트: {project_name} | 기간: {report.period_label} | "
            f"기준일: {report.data_date} | 버전 v{report.schedule_version} | 양식: {report.template_name}",
            size_half_pt=18,
            color="566175",
            spacing_after=180,
        ),
    ]
    for blk in report.blocks_json:
        body.append(_w_p(str(blk.get("heading", "")), bold=True, size_half_pt=25, color="1B2845", spacing_after=80))
        kind = blk.get("block_kind")
        if kind == "kpi":
            metrics = blk.get("metrics") or []
            if metrics:
                body.append(
                    _w_table(
                        ["지표", "값", "참고"],
                        [[m.get("label", ""), m.get("value", ""), m.get("sub", "")] for m in metrics],
                    )
                )
        elif kind == "table":
            tbl = blk.get("table") or {}
            cols = tbl.get("columns") or []
            rows = tbl.get("rows") or []
            if cols and rows:
                body.append(_w_table([str(c) for c in cols], rows))
            else:
                body.append(_w_p(str(blk.get("text") or "해당 자료가 없습니다."), color="566175"))
        elif kind == "chart":
            chart = blk.get("chart") or {}
            points = chart.get("points") or []
            if blk.get("text"):
                body.append(_w_p(str(blk["text"]), color="566175"))
            if points:
                if chart.get("kind") == "spi_trend":
                    body.append(_w_table(["기준일", "SPI"], [[p.get("date"), p.get("spi")] for p in points[-12:]]))
                else:
                    body.append(
                        _w_table(
                            ["기준일", "계획 누적(%)", "실적 누적(%)", "예측 누적(%)"],
                            [[p.get("date"), p.get("plan_cum"), p.get("actual_cum") if p.get("actual_cum") is not None else "—", p.get("forecast_cum") if p.get("forecast_cum") is not None else "—"] for p in points[-12:]],
                        )
                    )
        else:
            raw_text = str(blk.get("text") or "").strip() or "(내용 없음)"
            for line in raw_text.splitlines():
                if line.strip():
                    body.append(_w_p(line, spacing_after=60))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types.encode("utf-8"))
        z.writestr("_rels/.rels", rels.encode("utf-8"))
        z.writestr("word/document.xml", document_xml.encode("utf-8"))
    return buf.getvalue()
