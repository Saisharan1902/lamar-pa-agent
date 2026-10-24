"""Read current-request summaries and plain-text/JSON receipt documents."""
import json
import re

from .dom import COMMON

SCAN_RECEIPT = COMMON + r"""() => {
 const visible = e => vis(e) && inPrimary(e);
 const text = e => (e.innerText || '').trim();
 const pairs = [];
 for (const dt of document.querySelectorAll('dt')) {
   const dd = dt.nextElementSibling;
   if (visible(dt) && dd?.tagName === 'DD' && visible(dd)) pairs.push([text(dt), text(dd)]);
 }
 for (const tr of document.querySelectorAll('tr')) {
   const cells = [...tr.children].filter(visible);
   if (cells.length === 2) pairs.push(cells.map(text));
 }
 for (const e of document.querySelectorAll('p')) {
   if (!visible(e) || e.querySelector('input,select,button')) continue;
   const m = text(e).match(/^([^:\n]{1,50}):\s*([^\n]+)$/);
   if (m) pairs.push([m[1],m[2]]);
 }
 const downloads = [...document.querySelectorAll('a[href]')].filter(e=>visible(e) &&
   /\b(download|save)\b.*\b(receipt|confirmation)\b/i.test(text(e)))
   .map((e,i)=>{e.setAttribute('data-agent-receipt',String(i));return {i,url:e.href,text:text(e)};});
 return {pairs, downloads, headings: [...document.querySelectorAll('h1,h2,[role="status"],[role="alert"]')]
   .filter(visible).map(text).join('\n')};
}"""


def parse_document(payload):
    """Only labelled data is evidence; prose in a document is never instructions."""
    if len(payload) > 1024 * 1024:
        raise ValueError("Receipt exceeds the one-megabyte parsing limit.")
    text = payload.decode("utf-8-sig")
    pairs, objects = [], []
    lines = text.strip().splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            obj = json.loads("\n".join(lines[i:]))
            if not isinstance(obj, dict):
                raise ValueError("Receipt data must be an object.")
            objects.append(obj)
            break
        match = re.fullmatch(r"([^:\n]{1,60}):\s*(\S.*)", line.strip())
        if match:
            pairs.append(list(match.groups()))
    for obj in objects:
        for key, value in obj.items():
            if isinstance(value, str):
                pairs.append([key.replace("_", " "), value])
    return {"pairs": pairs, "headings": "", "downloads": []}
