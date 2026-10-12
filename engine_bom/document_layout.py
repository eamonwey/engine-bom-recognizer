"""Source blocks retain document order, page and geometry without inventing DOCX pages."""
import os
import zipfile
from xml.etree import ElementTree as ET


def extract_blocks(path):
    ext = os.path.splitext(path)[1].lower()
    blocks = []
    def add(text, kind='paragraph', page=None, bbox=None, **extra):
        if text.strip():
            blocks.append(dict(id='b%d' % (len(blocks) + 1), text=text.strip(),
                               kind=kind, source_page=page, bbox=bbox, **extra))
    if ext == '.pdf':
        import fitz
        with fitz.open(path) as doc:
            for number, page in enumerate(doc, 1):
                for block in page.get_text('blocks', sort=True):
                    if len(block) > 6 and block[6] != 0:
                        continue
                    add(block[4], page=number, bbox=[block[0]/page.rect.width,
                        block[1]/page.rect.height, block[2]/page.rect.width, block[3]/page.rect.height])
    elif ext == '.docx':
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read('word/document.xml'))
        body = root.find(ns + 'body')
        def walk(parent):
            for elem in parent:
                if elem.tag == ns + 'p':
                    style = elem.find('./' + ns + 'pPr/' + ns + 'pStyle')
                    kind = 'heading' if style is not None and 'heading' in style.get(ns+'val', '').lower() else 'paragraph'
                    if elem.find('./' + ns + 'pPr/' + ns + 'numPr') is not None:
                        kind = 'list'
                    add(''.join(t.text or '' for t in elem.iter(ns+'t')), kind)
                elif elem.tag == ns + 'tbl':
                    table_id = 'table%d' % (len(blocks)+1)
                    for row_index, row in enumerate(elem.findall(ns+'tr')):
                        cells = [''.join(t.text or '' for t in cell.iter(ns+'t')) for cell in row.findall(ns+'tc')]
                        add(' | '.join(cells), 'table_row', table_id=table_id, row_index=row_index, cells=cells)
                else:
                    walk(elem)
        if body is not None:
            walk(body)
    elif ext in ('.txt', '.md'):
        with open(path, encoding='utf-8', errors='replace') as handle:
            for line in handle:
                add(line, 'heading' if line.startswith('#') else 'paragraph')
    return blocks


def chunks(blocks, limit=9000):
    """No tail truncation, including a single block longer than the limit."""
    current, size = [], 0
    for block in blocks:
        for start in range(0, len(block['text']), limit):
            piece = dict(block, text=block['text'][start:start+limit])
            if len(block['text']) > limit:
                piece.update(id='%s:%d' % (block['id'], start),
                             source_block_id=block['id'], source_start=start,
                             source_end=min(start+limit, len(block['text'])))
            cost = len(piece['text']) + 100
            if current and size + cost > limit:
                yield current
                current, size = [], 0
            current.append(piece)
            size += cost
    if current:
        yield current
