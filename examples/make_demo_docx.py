"""Build examples/demo_manuscript.docx (Word heading styles) from demo_manuscript.md. The demo text is original."""
import os
import re

import docx

here = os.path.dirname(os.path.abspath(__file__))
d = docx.Document()
for line in open(os.path.join(here, "demo_manuscript.md"), encoding="utf-8"):
    line = line.rstrip()
    if not line:
        continue
    m = re.match(r"^(#+)\s+(.*)", line)
    if m and not d.paragraphs:
        d.add_heading(m.group(2), 0)
    elif m:
        d.add_heading(m.group(2), len(m.group(1)))
    else:
        d.add_paragraph(line)
d.save(os.path.join(here, "demo_manuscript.docx"))
