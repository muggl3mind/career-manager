#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from docx import Document
from docx.shared import Pt

"""
Run-aware safe patcher with bold-safe replacement and hyperlink support.

Fixes applied:
- Bold inheritance: new runs mirror font/size only, never bold/italic from run[0]
- Bold-header pattern: "Header: continuation" rebuilt as two explicit runs
- Hyperlink-aware clearing: removes both <w:r> and <w:hyperlink> children
- insert_hyperlink() helper for adding clickable links
"""


def _get_run_font_props(runs: list) -> tuple:
    """Return (font_name, font_size_pt) from first run that has them set."""
    for r in runs:
        name = r.font.name
        size = r.font.size
        if name or size:
            size_pt = (size / 12700) if size else None  # EMU to pt
            return name, size_pt
    return None, None


def _clear_paragraph_runs(paragraph) -> None:
    """Remove all <w:r> and <w:hyperlink> direct children from paragraph XML."""
    from lxml import etree
    p_elem = paragraph._p
    to_remove = []
    for child in p_elem:
        tag = etree.QName(child.tag).localname
        if tag in ('r', 'hyperlink'):
            to_remove.append(child)
    for child in to_remove:
        p_elem.remove(child)


def _has_bold_header_pattern(text: str) -> bool:
    """True if text looks like 'Short Header: longer continuation' (5 words or fewer before colon)."""
    if ': ' not in text:
        return False
    prefix = text.split(': ', 1)[0]
    return len(prefix.split()) <= 5


def _get_para_size_pt(paragraph) -> float | None:
    """Fallback: read font size from paragraph-level rPr (pPr/rPr/sz)."""
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    pPr = paragraph._p.pPr
    if pPr is None:
        return None
    pPr_rPr = pPr.find(f'{{{ns}}}rPr')
    if pPr_rPr is None:
        return None
    sz = pPr_rPr.find(f'{{{ns}}}sz')
    if sz is None:
        return None
    val = sz.get(f'{{{ns}}}val')
    return int(val) / 2 if val else None  # half-points to points


def _apply_size(run, font_size_pt: float | None, paragraph) -> None:
    """Set run font size, falling back to paragraph-level rPr if needed. Never leaves sz=0."""
    target_pt = font_size_pt or _get_para_size_pt(paragraph)
    if target_pt:
        run.font.size = Pt(target_pt)
    # Guard: if size ended up 0 (pipeline edge case), clear it so Word inherits correctly.
    if run.font.size == 0:
        run.font.size = None


def _redistribute_text_to_runs(paragraph, new_text: str) -> None:
    """Replace paragraph content preserving font/size but never inheriting bold/italic."""
    original_runs = list(paragraph.runs)
    font_name, font_size_pt = _get_run_font_props(original_runs)

    _clear_paragraph_runs(paragraph)

    if _has_bold_header_pattern(new_text):
        header, continuation = new_text.split(': ', 1)
        bold_run = paragraph.add_run(header + ': ')
        bold_run.bold = True
        if font_name:
            bold_run.font.name = font_name
        _apply_size(bold_run, font_size_pt, paragraph)
        normal_run = paragraph.add_run(continuation)
        normal_run.bold = False
        normal_run.italic = False
        if font_name:
            normal_run.font.name = font_name
        _apply_size(normal_run, font_size_pt, paragraph)
    else:
        run = paragraph.add_run(new_text)
        run.bold = False
        run.italic = False
        if font_name:
            run.font.name = font_name
        _apply_size(run, font_size_pt, paragraph)


def insert_hyperlink(paragraph, text: str, url: str,
                     font_name: str | None = None,
                     font_size_pt: float | None = None,
                     style: str = 'plain') -> None:
    """
    Insert a hyperlink run into a paragraph.

    style='plain'  — no colour/underline (for contact lines)
    style='styled' — blue + underline (for body citations/publications)

    Font name and size are applied explicitly to prevent fallback to document default.
    """
    from docx.oxml.ns import qn
    from lxml import etree

    part = paragraph.part
    r_id = part.relate_to(
        url,
        'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',
        is_external=True,
    )

    hyperlink = etree.SubElement(paragraph._p, qn('w:hyperlink'))
    hyperlink.set(qn('r:id'), r_id)

    run_elem = etree.SubElement(hyperlink, qn('w:r'))
    rpr = etree.SubElement(run_elem, qn('w:rPr'))

    if font_name:
        rFonts = etree.SubElement(rpr, qn('w:rFonts'))
        rFonts.set(qn('w:ascii'), font_name)
        rFonts.set(qn('w:hAnsi'), font_name)

    if font_size_pt:
        sz_val = str(int(font_size_pt * 2))
        sz_elem = etree.SubElement(rpr, qn('w:sz'))
        sz_elem.set(qn('w:val'), sz_val)
        szCs_elem = etree.SubElement(rpr, qn('w:szCs'))
        szCs_elem.set(qn('w:val'), sz_val)

    if style == 'styled':
        color = etree.SubElement(rpr, qn('w:color'))
        color.set(qn('w:val'), '0563C1')
        u = etree.SubElement(rpr, qn('w:u'))
        u.set(qn('w:val'), 'single')

    t = etree.SubElement(run_elem, qn('w:t'))
    t.text = text
    if text.startswith(' ') or text.endswith(' '):
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def apply_safe_patch(src: Path, dst: Path, repls: list[dict]) -> dict:
    d = Document(str(src))
    changed = []

    for para_idx, p in enumerate(d.paragraphs):
        full = "".join(r.text or "" for r in p.runs) if p.runs else p.text or ""
        if not full:
            continue

        updated = full
        local_changes = []
        for rep in repls:
            old = rep.get('old', '')
            new = rep.get('new', '')
            if old and old in updated:
                updated = updated.replace(old, new, 1)
                local_changes.append({'old': old, 'new': new})

        if updated != full:
            _redistribute_text_to_runs(p, updated)
            for ch in local_changes:
                changed.append({
                    'paragraph': para_idx,
                    'old': ch['old'],
                    'new': ch['new']
                })

    d.save(str(dst))
    return {'changed_count': len(changed), 'changes': changed}


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 4:
        print('Usage: docx_safe_patch.py <input.docx> <output.docx> <replacements.json>')
        raise SystemExit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    cfg = json.loads(Path(sys.argv[3]).read_text())
    result = apply_safe_patch(src, dst, cfg.get('replacements', []))
    print(json.dumps(result, indent=2))
