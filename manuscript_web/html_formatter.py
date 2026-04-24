"""서식 미리보기 — _build_document로 만든 docx 문서를 HTML로 직렬화.

docx_formatter.py는 건드리지 않음. 이미 검증된 서식 파이프라인을
그대로 재사용해서 웹에서도 워드와 동일한 결과(색상/형광펜/인용구 등)를 보여준다.
"""
from docx_formatter import _build_document


# WD_COLOR_INDEX → CSS 배경색
def _highlight_map():
    from docx.enum.text import WD_COLOR_INDEX
    return {
        WD_COLOR_INDEX.YELLOW: '#FFFF00',
        WD_COLOR_INDEX.BLACK: '#000000',
        WD_COLOR_INDEX.TURQUOISE: '#40E0D0',
        WD_COLOR_INDEX.BLUE: '#0000FF',
        WD_COLOR_INDEX.RED: '#FF0000',
        WD_COLOR_INDEX.GREEN: '#00FF00',
        WD_COLOR_INDEX.BRIGHT_GREEN: '#00FF00',
        WD_COLOR_INDEX.TEAL: '#008080',
        WD_COLOR_INDEX.PINK: '#FFC0CB',
        WD_COLOR_INDEX.DARK_YELLOW: '#808000',
        WD_COLOR_INDEX.DARK_BLUE: '#00008B',
        WD_COLOR_INDEX.DARK_RED: '#8B0000',
        WD_COLOR_INDEX.GRAY_25: '#C0C0C0',
        WD_COLOR_INDEX.GRAY_50: '#808080',
        WD_COLOR_INDEX.VIOLET: '#EE82EE',
        WD_COLOR_INDEX.WHITE: '#FFFFFF',
    }


def _escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


def _run_html(run, hl_map):
    styles = []
    if run.bold:
        styles.append('font-weight:700')
    if run.italic:
        styles.append('font-style:italic')
    if run.underline:
        styles.append('text-decoration:underline')
    fs = run.font.size
    if fs is not None:
        pt = fs.pt
        pt_str = f'{pt:g}'  # 24.0 → '24', 11.5 → '11.5'
        styles.append(f'font-size:{pt_str}pt')
    rgb = run.font.color.rgb
    if rgb is not None:
        styles.append(f'color:#{str(rgb)}')
    hl = run.font.highlight_color
    if hl is not None and hl in hl_map:
        styles.append(f'background-color:{hl_map[hl]}')
    text = _escape(run.text or '')
    if not text:
        return ''
    if not styles:
        return text
    return f'<span style="{";".join(styles)}">{text}</span>'


def _para_border_color(paragraph):
    """인용구 왼쪽 테두리 색상 (w:pBdr/w:left)."""
    from docx.oxml.ns import qn
    pPr = paragraph._element.find(qn('w:pPr'))
    if pPr is None:
        return None
    pBdr = pPr.find(qn('w:pBdr'))
    if pBdr is None:
        return None
    left = pBdr.find(qn('w:left'))
    if left is None:
        return None
    return left.get(qn('w:color'))


def _paragraph_html(paragraph, hl_map):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    style_name = paragraph.style.name if paragraph.style else ''
    tag = 'div'
    extra_css = []
    if style_name.startswith('Heading 1'):
        tag = 'h1'
        extra_css.append('font-size:22pt;margin:14px 0 8px')
    elif style_name.startswith('Heading 2'):
        tag = 'h2'
        extra_css.append('font-size:18pt;margin:12px 0 6px')
    elif style_name.startswith('Heading 3'):
        tag = 'h3'
        extra_css.append('font-size:15pt;margin:10px 0 4px')

    runs_html = ''.join(_run_html(r, hl_map) for r in paragraph.runs)
    if not runs_html:
        runs_html = '&nbsp;'

    border_color = _para_border_color(paragraph)
    if border_color:
        extra_css.append(
            f'border-left:4px solid #{border_color};'
            f'padding:6px 12px;background:#f8fafc;margin:8px 0'
        )
    align = paragraph.alignment
    if align == WD_ALIGN_PARAGRAPH.CENTER:
        extra_css.append('text-align:center')

    if tag == 'div' and not extra_css:
        extra_css.append('margin:2px 0')

    style_attr = f' style="{";".join(extra_css)}"' if extra_css else ''
    return f'<{tag}{style_attr}>{runs_html}</{tag}>'


def _table_html(table, hl_map):
    """블로거 요청박스 — 빨간 테두리 + 노란 배경."""
    cell = table.rows[0].cells[0]
    parts = []
    for para in cell.paragraphs:
        runs_html = ''.join(_run_html(r, hl_map) for r in para.runs)
        if runs_html.strip():
            parts.append(f'<div style="margin:2px 0">{runs_html}</div>')
    body = '\n'.join(parts) or '&nbsp;'
    return (
        '<div style="border:2px solid #FF0000;background:#FFF8E1;'
        'padding:12px;margin:14px 0;border-radius:4px">' + body + '</div>'
    )


def build_html_preview(title, body):
    """제목 + 본문 텍스트 → 서식 적용된 HTML 문자열."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    # 미리보기는 편집창 원문 그대로 렌더링 — 정규화를 재적용하지 않아야
    # 사용자가 수동으로 쪼갠 줄바꿈이 미리보기에서 되돌아가지 않음.
    doc = _build_document(body or '', normalize=False)
    hl_map = _highlight_map()
    parts = []
    if title:
        parts.append(
            f'<h1 style="font-size:20pt;font-weight:700;margin:0 0 16px;'
            f'padding-bottom:10px;border-bottom:2px solid #e2e8f0;'
            f'color:#1e293b">{_escape(title)}</h1>'
        )
    for child in doc.element.body.iterchildren():
        if child.tag == qn('w:p'):
            parts.append(_paragraph_html(Paragraph(child, doc), hl_map))
        elif child.tag == qn('w:tbl'):
            parts.append(_table_html(Table(child, doc), hl_map))
    return '\n'.join(parts)
