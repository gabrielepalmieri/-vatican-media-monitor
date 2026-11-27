"""Create the downloadable morning PDF with source links and Unicode fonts."""
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether


def write_pdf(edition, root):
    directory = Path(root)/'rassegne'
    directory.mkdir(exist_ok=True)
    output = directory/('rassegna-'+edition['date']+'.pdf')
    fonts = Path('/usr/share/fonts/truetype/dejavu')
    regular, bold = 'Helvetica', 'Helvetica-Bold'
    if (fonts/'DejaVuSans.ttf').exists() and (fonts/'DejaVuSans-Bold.ttf').exists():
        regular, bold = 'DigestSans', 'DigestSansBold'
        if regular not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(regular, str(fonts/'DejaVuSans.ttf')))
            pdfmetrics.registerFont(TTFont(bold, str(fonts/'DejaVuSans-Bold.ttf')))
        pdfmetrics.registerFontFamily(regular, normal=regular, bold=bold, italic=regular, boldItalic=bold)
    navy = colors.HexColor('#173d70')
    text_style = ParagraphStyle('text', fontName=regular, fontSize=10, leading=14, textColor=colors.HexColor('#263444'), spaceAfter=3*mm)
    heading = ParagraphStyle('section', parent=text_style, fontName=bold, fontSize=22, leading=28, textColor=navy, spaceAfter=7*mm)
    title = ParagraphStyle('title', parent=text_style, fontName=bold, fontSize=12, leading=16, spaceAfter=2*mm)
    meta = ParagraphStyle('meta', parent=text_style, fontSize=8.5, leading=12, textColor=colors.HexColor('#526174'), spaceAfter=1.5*mm)
    date = datetime.fromisoformat(edition['date'])
    months = 'gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre'.split()
    label = f'{date.day} {months[date.month-1]} {date.year}'
    cutoff = datetime.fromisoformat(edition['coverage_to']).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Rome'))
    section_names = ' · '.join(section['title'] for section in edition['sections'])
    document = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=19*mm, leftMargin=19*mm,
                                 topMargin=31*mm, bottomMargin=20*mm, title=f'Rassegna del mattino - {label}',
                                 author='Vatican Media Monitor', pageCompression=1)
    story = []
    for number, section in enumerate(edition['sections']):
        if number:
            story.append(PageBreak())
        story.append(Paragraph(escape(section['title']), heading))
        if not section['items']:
            story.append(Paragraph('Nessun articolo recente disponibile per questa sezione.', text_style))
        for item in section['items']:
            stamp = datetime.fromisoformat(item['published']).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Rome'))
            byline = item['source'] + (' · '+item['author'] if item.get('author') and item['author'].casefold() not in item['source'].casefold() else '')
            blocks = [Paragraph(escape(byline+' · '+stamp.strftime('%d/%m, %H:%M')),meta),
                      Paragraph(escape(item['title']),title)]
            if item.get('summary'):
                blocks.append(Paragraph(escape(item['summary']),text_style))
            blocks.append(Paragraph('<link href="'+escape(item['url'], {'"':'&quot;'})+'" color="#173d70">Leggi l’articolo originale</link>',meta))
            blocks.append(Spacer(1,4*mm))
            story.append(KeepTogether(blocks))

    def header(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(navy)
        canvas.setFont(bold,12)
        canvas.drawString(19*mm,A4[1]-16*mm,'Rassegna del mattino')
        canvas.setFont(regular,9)
        canvas.drawRightString(A4[0]-19*mm,A4[1]-16*mm,label+' | Edizione delle 7')
        canvas.setStrokeColor(colors.HexColor('#d8b45a'))
        canvas.line(19*mm,A4[1]-21*mm,A4[0]-19*mm,A4[1]-21*mm)
        canvas.setFont(regular,8)
        canvas.setFillColor(colors.HexColor('#526174'))
        canvas.drawString(19*mm,12*mm,'Vatican Media Monitor · Notizie fino al '+cutoff.strftime('%d/%m alle %H:%M'))
        canvas.drawRightString(A4[0]-19*mm,12*mm,str(doc.page))
        canvas.restoreState()

    document.build(story,onFirstPage=header,onLaterPages=header)
    edition['pdf_url'] = 'rassegne/'+output.name
    return output
