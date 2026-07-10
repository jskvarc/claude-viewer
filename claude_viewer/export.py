"""Export a conversation to PDF."""
from __future__ import annotations

import re
from pathlib import Path

import markdown as md
from fpdf import FPDF

from . import store

_DEJAVU_DIR = Path('/usr/share/fonts/truetype/dejavu')
_USER_COLOR = (21, 101, 192)
_ASSISTANT_COLOR = (0, 121, 107)
_META_COLOR = (120, 120, 120)
_TEXT_COLOR = (30, 30, 30)


class _ConversationPDF(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format='A4')
        self.doc_title = title
        self.set_auto_page_break(True, margin=18)
        self.alias_nb_pages()
        # DejaVu gives full Unicode support; fall back to core fonts
        # (latin-1 only) if it is not installed.
        if (_DEJAVU_DIR / 'DejaVuSans.ttf').exists():
            self.add_font('doc', '', str(_DEJAVU_DIR / 'DejaVuSans.ttf'))
            self.add_font('doc', 'B', str(_DEJAVU_DIR / 'DejaVuSans-Bold.ttf'))
            self.add_font('doc', 'I', str(_DEJAVU_DIR / 'DejaVuSans-Oblique.ttf'))
            self.add_font('doc', 'BI', str(_DEJAVU_DIR / 'DejaVuSans-BoldOblique.ttf'))
            self.add_font('docmono', '', str(_DEJAVU_DIR / 'DejaVuSansMono.ttf'))
            self.add_font('docmono', 'B', str(_DEJAVU_DIR / 'DejaVuSansMono-Bold.ttf'))
            self.family_main, self.family_mono = 'doc', 'docmono'
        else:
            self.family_main, self.family_mono = 'helvetica', 'courier'

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font(self.family_main, 'I', 8)
        self.set_text_color(*_META_COLOR)
        self.cell(0, 5, self.doc_title[:90], align='C', new_x='LMARGIN', new_y='NEXT')
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(self.family_main, 'I', 8)
        self.set_text_color(*_META_COLOR)
        self.cell(0, 5, f'Page {self.page_no()}/{{nb}}', align='C')


# fenced code blocks and inline code spans (odd indices after split)
_CODE_RE = re.compile(r'(```.*?```|`[^`\n]*`)', re.DOTALL)


def _escape_html_outside_code(text: str) -> str:
    """Neutralize raw HTML so literal tags in messages survive the renderer;
    markdown already escapes the inside of code blocks itself."""
    parts = _CODE_RE.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace('&', '&amp;').replace('<', '&lt;')
    return ''.join(parts)


def _write_markdown(pdf: _ConversationPDF, text: str) -> None:
    body = md.markdown(_escape_html_outside_code(text),
                       extensions=['fenced_code', 'tables', 'nl2br'])
    try:
        pdf.write_html(body, font_family=pdf.family_main, pre_code_font=pdf.family_mono)
    except TypeError:  # older fpdf2 without these keyword arguments
        pdf.write_html(body)


def session_to_pdf(project_path: str, data: store.SessionData, include_tools: bool = False) -> bytes:
    pdf = _ConversationPDF(data.title)
    pdf.add_page()

    pdf.set_font(pdf.family_main, 'B', 16)
    pdf.set_text_color(*_TEXT_COLOR)
    pdf.multi_cell(0, 8, data.title, new_x='LMARGIN', new_y='NEXT')
    pdf.set_font(pdf.family_main, '', 9)
    pdf.set_text_color(*_META_COLOR)
    period = f'{store.format_timestamp(data.started)} – {store.format_timestamp(data.ended)}'
    pdf.multi_cell(0, 5, f'{project_path} · {period} · {data.prompt_count} prompt(s)', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)

    for message in data.messages:
        if message.role == 'tool':
            if not include_tools:
                continue
            pdf.set_font(pdf.family_mono, '', 7.5)
            pdf.set_text_color(*_META_COLOR)
            pdf.multi_cell(0, 4, f'[tool] {message.text}', new_x='LMARGIN', new_y='NEXT')
            pdf.ln(1)
            continue
        is_user = message.role == 'user'
        pdf.set_font(pdf.family_main, 'B', 10)
        pdf.set_text_color(*(_USER_COLOR if is_user else _ASSISTANT_COLOR))
        header = f'{"You" if is_user else "Claude"} — {store.format_timestamp(message.timestamp)}'
        pdf.cell(0, 6, header, new_x='LMARGIN', new_y='NEXT')
        pdf.set_font(pdf.family_main, '', 10)
        pdf.set_text_color(*_TEXT_COLOR)
        try:
            _write_markdown(pdf, message.text)
        except Exception:  # noqa: BLE001 - never lose a message over formatting
            pdf.set_font(pdf.family_main, '', 10)
            pdf.set_text_color(*_TEXT_COLOR)
            pdf.multi_cell(0, 5, message.text, new_x='LMARGIN', new_y='NEXT')
        pdf.ln(3)

    return bytes(pdf.output())


def pdf_filename(title: str) -> str:
    safe = re.sub(r'[^\w-]+', '_', title).strip('_')[:60] or 'conversation'
    return f'{safe}.pdf'
