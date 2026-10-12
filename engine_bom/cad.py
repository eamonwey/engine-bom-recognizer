"""Local DXF rendering; each nonempty paper layout is a page, otherwise model space."""
import io
import threading
_RENDER_LOCK = threading.Lock()


def render_dxf(path, cfg):
    import ezdxf
    from ezdxf.addons.drawing.matplotlib import qsave
    from PIL import Image
    from .ingestion import PageImage, _resize_if_needed
    drawing = ezdxf.readfile(path)
    layouts = [layout for layout in drawing.layouts if layout.name != 'Model' and len(layout)]
    layouts = layouts or [drawing.modelspace()]
    pages = []
    import tempfile
    import os
    with _RENDER_LOCK, tempfile.TemporaryDirectory() as folder:
        for n, layout in enumerate(layouts, 1):
            target = os.path.join(folder, '%d.png' % n)
            qsave(layout, target, bg='#ffffff', fg='#000000', dpi=int(cfg.get('dpi', 200)))
            with Image.open(target) as image:
                rendered = _resize_if_needed(image.convert('RGB'), cfg)
            pages.append(PageImage(n, rendered, layout.name))
    return pages
