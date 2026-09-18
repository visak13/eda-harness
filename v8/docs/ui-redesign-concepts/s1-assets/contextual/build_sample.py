"""Small in-context proposal, copied from exact approved-direction static composition.
Not runtime UI or image_gen output. Does not alter original references.
"""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
source = (BASE / 'revision3-clean-specimen.html').read_text(encoding='utf-8')
# Keep actual existing human and agent avatars, not the rejected robot substitutes.
source = source.replace('src="specimen-', 'src="../../specimen-')
source = source.replace('Board — static proposed design specimen', 'Board — contextual icon proposal for architect review')
# Conventional forms: project collection, task list, document, file folder, past events.
symbols = {
 'epic': '<rect x="6" y="7" width="15" height="14" rx="2"/><path d="M17 7V3H3v14h3M10 12h7m-7 4h5"/>',
 'work-list': '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 8h.01M11 8h6M7 12h.01M11 12h6M7 16h.01M11 16h4"/>',
 'file-folder': '<path d="M3 8V5h7l3 3h8v12H3ZM3 11h18"/>',
 'past-events': '<path d="M3 10a9 9 0 1 1 1 8M3 4v6h6M12 6v6l4 2"/>',
 # Play = work started, not half a progress percentage or a clock shared with History.
 'progress': '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4Z" fill="currentColor" stroke="none"/>',
 'review-request': '<path d="M3 4h18v13H9l-6 4ZM7 8h10M7 12h7"/>',
}
for name, body in symbols.items():
    markup = f'<symbol id="{name}" viewBox="0 0 24 24">{body}</symbol>'
    pattern = rf'<symbol id="{re.escape(name)}"[^>]*>.*?</symbol>'
    if re.search(pattern, source):
        source = re.sub(pattern, lambda _: markup, source)
    else:
        source = source.replace('</defs>', markup + '</defs>')
changes = {
 '<svg><use href="#clip"/></svg>Files &amp; evidence': '<svg><use href="#file-folder"/></svg>Files &amp; evidence',
 '<svg><use href="#clock"/></svg>History': '<svg><use href="#past-events"/></svg>History',
 '<svg><use href="#epic"/></svg>Work': '<svg><use href="#work-list"/></svg>Work',
 '<svg class="i"><use href="#alert"/></svg>Review requested': '<svg class="i"><use href="#review-request"/></svg>Review requested',
 'PROPOSED STATIC MOCKUP · SYNTHETIC CONTENT · NOT THE RUNNING BOARD': 'CONTEXTUAL ICON PROPOSAL · EXISTING AVATARS PRESERVED · STATIC, NOT RUNNING APP',
}
for old, new in changes.items():
    assert source.count(old) == 1, old
    source = source.replace(old, new)
# Functional illustration sizes are unchanged from the source: 20px controls / 18px statuses.
# Show sample meaning in conversation context without adding fake operations or dashboard cards.
source = source.replace('Here’s a compact sketch. Your design review stays one click away, and feedback comes back to this thread.', 'The document opens Design; the folder collects Files &amp; evidence. History shows earlier events; Work opens the task list.')
(HERE / 'sample.html').write_text(source, encoding='utf-8')
print('Wrote contextual sample: original layout/avatar assets retained, six semantic symbol changes; no generation or runtime edits.')
