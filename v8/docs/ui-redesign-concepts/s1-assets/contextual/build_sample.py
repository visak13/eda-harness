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
 # Static unfilled activity ring: no play button, elapsed time or numeric percentage.
 'progress': '<path d="M12 3a9 9 0 1 1-9 9"/><path d="M3.5 7h.01M7 3.5h.01"/>',
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
source = source.replace('<button class="plain"><svg><use href="#expand"/></svg></button>', '<button class="plain"><svg><use href="#expand"/></svg>Expand</button>')
source = source.replace('</style>', '''
/* Contextual review adaptations only: desktop light baseline remains unchanged. */
body.dark{background:#000;color:#eeeae2}body.dark aside{background:#151515;border-color:#aaa49a}body.dark button,body.dark .composer,body.dark .review,body.dark .popover{background:#202020;color:#eeeae2;border-color:#aaa49a}body.dark aside button,body.dark .plain{background:transparent;border-color:transparent}body.dark aside .active{border-color:#aaa49a}body.dark .count{color:#29251f}body.dark aside .active,body.dark .badge{background:#4b4020;color:#fff0bd}body.dark .coral,body.dark .links .design,body.dark .request{background:#52362f;color:#ffe2d5}body.dark .approve{background:#30432b;color:#e5f3dd}body.dark .reviewfeedback{background:#171717}body.dark .textarea,body.dark .reviewfeedback .feedback-draft{background:#101010;color:#eeeae2;border-color:#aaa49a}body.dark .purpose,body.dark .label,body.dark .topline,body.dark .current,body.dark .account small,body.dark .by .to,body.dark .by time,body.dark .by .reply,body.dark .heading span,body.dark .caption,body.dark .delivery,body.dark .footer,body.dark .reviewmeta,body.dark .context,body.dark .saved{color:#c8c1b6}body.dark .current strong{color:#eeeae2}body.dark .composer-foot .send,body.dark .feedback-send>button:first-child{background:#eeeae2;color:#171717}body.dark .composer{box-shadow:2px 2px 0 #504b43}body.dark .sketch{color:#29251f}body.dark .divider{background:#706a60}body.dark .links,body.dark .reviewhead,body.dark .reviewfeedback,body.dark .context-note{border-color:#706a60}
@media(max-width:600px){
 .app{display:block;height:auto;min-height:100vh}aside{padding:12px;display:flex;flex-direction:row;align-items:center;flex-wrap:wrap;gap:4px;border-right:0;border-bottom:1px solid #39352e}.brand{font-size:22px;margin:0 12px 0 0}.brand svg{width:24px;height:24px}aside button{min-height:44px}.divider,.current{display:none}aside .lower{margin:0;display:flex;flex-wrap:wrap;gap:4px;width:100%;align-items:center}.account{margin-left:auto}.account small{font-size:11px}.account .avatar{width:28px;height:28px}main{padding:16px 12px;display:block}.topline{gap:8px}.topline>span{min-width:0;overflow-wrap:anywhere}h1{font-size:28px;margin-top:14px}.purpose{font-size:15px}.metadata{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}.label{font-size:11px}.value{flex-wrap:wrap;gap:5px}.badge{font-size:12px;padding:4px 6px}.links{flex-wrap:wrap;gap:4px;margin-top:14px;padding-bottom:12px}.links button{min-height:44px;padding:6px}.conversation{overflow:visible;padding-top:18px}.heading .end{display:none}.msg{gap:8px;grid-template-columns:28px minmax(0,1fr);margin-bottom:20px}.msg>.avatar{width:28px;height:28px}.by{flex-wrap:wrap;gap:5px}.by .reply{min-height:32px}.msg p{font-size:15px}.attachment{flex-direction:column;align-items:flex-start;gap:6px}.composer{margin-top:18px;padding:10px}.composer-top{flex-wrap:wrap;gap:6px}.composer-top .expand{margin-left:0}.composer-top button{min-height:44px}.composer-foot{flex-wrap:wrap;gap:4px}.composer-foot button{min-height:44px}.delivery{width:100%;order:3}.textarea{min-height:100px}.footer{font-size:10px;text-align:left}.review{width:calc(100vw - 16px);height:calc(100vh - 16px);overflow:auto}.reviewhead{padding:12px}.reviewtop,.reviewtitle{flex-wrap:wrap;gap:8px}.reviewtop div{flex-wrap:wrap}.reviewtitle .buttons{margin-left:0;flex-wrap:wrap}.reviewtitle h2{font-size:22px}.reviewbody{display:block;overflow:visible}.document,.reviewfeedback{padding:16px}.document{overflow:visible}.reviewfeedback{border-left:0;border-top:1px solid #c7bfae}.reviewfeedback .row{flex-wrap:wrap}
}
</style>''')
(HERE / 'sample.html').write_text(source, encoding='utf-8')
print('Wrote contextual sample: original layout/avatar assets retained, six semantic symbol changes; no generation or runtime edits.')
