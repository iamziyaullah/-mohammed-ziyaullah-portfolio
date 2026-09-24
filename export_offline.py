"""Export a self-contained PUBLIC preview for opening without a web server.

The editable content studio only works in the Flask application, not this HTML file.
Run: python export_offline.py
"""
import base64
import re
from pathlib import Path

from app import ROOT, app


def data_uri(path, media_type):
    blob = (ROOT / path).read_bytes()
    return f'data:{media_type};base64,{base64.b64encode(blob).decode("ascii")}'


def main():
    with app.test_client() as client:
        response = client.get('/')
        if response.status_code != 200:
            raise RuntimeError(f'Homepage returned HTTP {response.status_code}')
        html = response.get_data(as_text=True)

    css = (ROOT / 'static/site.css').read_text(encoding='utf-8')
    for name in ['dm-sans', 'instrument-serif-italic']:
        css = css.replace(
            f"url('/static/fonts/{name}.woff2')",
            f"url('{data_uri(f'static/fonts/{name}.woff2', 'font/woff2')}')",
        )
    css += """
.offline-info{padding:15px 0 19px;border-top:1px solid rgba(255,255,255,.13);color:#b8cfc4;font-size:11px;line-height:1.65}.offline-info strong{color:#e6bf7d}
.offline-admin-panel[hidden]{display:none!important}.offline-admin-panel{position:fixed;z-index:3000;inset:0;display:grid;place-items:center;padding:20px;background:rgba(4,21,27,.74);backdrop-filter:blur(8px)}
.offline-admin-card{width:min(100%,490px);padding:clamp(25px,5vw,39px);border:1px solid #d7e8d9;border-radius:12px;background:#fffefa;color:#163330;box-shadow:0 32px 90px rgba(0,0,0,.3)}
.offline-admin-card .offline-mark{font-size:23px;color:#b4894b}.offline-admin-card h2{margin:13px 0;font-size:32px;line-height:1.12;letter-spacing:-.05em}.offline-admin-card p{color:#526b61;font-size:14px;line-height:1.75}.offline-admin-card strong{color:#1c5246}.offline-admin-card button{margin-top:14px;padding:12px 19px;border:0;border-radius:6px;background:#123a34;color:#fff;font-weight:800}.offline-admin-card button:hover{background:#25654e}
body.offline-modal-open{overflow:hidden}
"""
    html = html.replace('<link rel="stylesheet" href="/static/site.css">', f'<style>\n{css}\n</style>')
    html = re.sub(
        r'(<img\b[^>]*\bsrc=")[^"]+',
        lambda match: match.group(1) + data_uri('static/images/ziyaullah.jpg', 'image/jpeg'),
        html, count=1,
    )
    script = (ROOT / 'static/site.js').read_text(encoding='utf-8')
    html = html.replace('<script src="/static/site.js" defer></script>', f'<script>\n{script}\n</script>')
    html = html.replace('<a href="/admin" rel="nofollow">Admin</a>', '<a href="#offline-info">Admin info</a>')
    html = html.replace('class="nav-admin" href="/admin/login"', 'class="nav-admin" href="#offline-info"')
    html = html.replace(
        '<div class="footer-bottom">',
        '<div class="offline-info" id="offline-info"><strong>OFFLINE PREVIEW:</strong> '
        'This file shows the public website. The editable admin panel requires the included Flask server; '
        'open /admin on the running site.</div><div class="footer-bottom">',
    )
    offline_admin = '''
<div class="offline-admin-panel" id="offline-admin-panel" hidden role="presentation">
  <div class="offline-admin-card" role="dialog" aria-modal="true" aria-labelledby="offline-admin-title" aria-describedby="offline-admin-help">
    <span class="offline-mark" aria-hidden="true">✳</span>
    <h2 id="offline-admin-title">Admin yahan nahi khulega.</h2>
    <p id="offline-admin-help">Ye <strong>offline HTML sirf website ka preview</strong> hai. Secure login aur changes save karne ke liye server chahiye. Arena mein <strong>live website preview</strong> kholo aur uske header par Admin dabao. Apne computer par real admin seedha kholne ke liye full ZIP extract karke Windows par <strong>RUN-ADMIN.bat</strong> (macOS/Linux par <strong>sh RUN-ADMIN.sh</strong>) chalao. Python 3.10+ chahiye, aur terminal khula rehna chahiye.</p>
    <button type="button" id="offline-admin-close">Samajh gaya</button>
  </div>
</div>
<script>
(() => {
  const panel = document.getElementById('offline-admin-panel');
  const close = document.getElementById('offline-admin-close');
  let previousFocus;
  document.querySelectorAll('a[href="#offline-info"]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault(); previousFocus = document.activeElement;
    panel.hidden = false; document.body.classList.add('offline-modal-open'); close.focus();
  }));
  const dismiss = () => { panel.hidden = true; document.body.classList.remove('offline-modal-open'); previousFocus?.focus(); };
  close.addEventListener('click', dismiss);
  panel.addEventListener('click', event => { if (event.target === panel) dismiss(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) dismiss(); });
})();
</script>
'''
    html = html.replace('</body>', offline_admin + '</body>')
    output = ROOT / 'OPEN-ZIYAULLAH-PREMIUM.html'
    output.write_text(html, encoding='utf-8')
    print(f'Exported standalone public preview: {output.name} ({output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
