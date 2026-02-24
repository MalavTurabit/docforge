import streamlit as st
import requests
from datetime import datetime
import markdown as md_lib

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="DocForge",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"] {
    background: #f0f2f7 !important;
    font-family: 'Inter', sans-serif !important;
    color: #111827 !important;
}
#MainMenu, footer, header,
[data-testid="stToolbar"],
[data-testid="stDecoration"] { display: none !important; }

/* ── SIDEBAR dark blue ── */
section[data-testid="stSidebar"] {
    background: #0d1f3c !important;
    min-width: 240px !important;
    max-width: 240px !important;
}
section[data-testid="stSidebar"] > div:first-child {
    background: #0d1f3c !important;
    padding: 0 !important;
}

/* Streamlit's own collapse button — restyle as our toggle */
[data-testid="stSidebarCollapseButton"] {
    background: transparent !important;
    border: none !important;
    position: absolute !important;
    top: 14px !important;
    right: -20px !important;
}
[data-testid="stSidebarCollapseButton"] svg {
    fill: #0d1f3c !important;
    width: 20px !important; height: 20px !important;
}
[data-testid="collapsedControl"] {
    background: #0d1f3c !important;
    border-radius: 0 8px 8px 0 !important;
}
[data-testid="collapsedControl"] svg { fill: white !important; }

/* remove default streamlit sidebar padding/gaps */
[data-testid="stSidebar"] .block-container { padding: 0 !important; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] { padding: 0 !important; }

/* ── Main content ── */
.block-container { padding: 2rem 2.5rem !important; max-width: 100% !important; }

/* ── Inputs ── */
[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input {
    background: #fff !important; border: 1.5px solid #d1d5db !important;
    border-radius: 8px !important; color: #111827 !important;
    caret-color: #111827 !important; font-size: 0.84rem !important;
}
[data-testid="stTextArea"] textarea:focus,
[data-testid="stTextInput"] input:focus {
    border-color: #4f6ef7 !important;
    box-shadow: 0 0 0 3px rgba(79,110,247,0.1) !important;
    color: #111827 !important; caret-color: #111827 !important;
}
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stTextInput"] input::placeholder { color: #9ca3af !important; }
[data-testid="stSelectbox"] > div > div {
    background: #fff !important; border: 1.5px solid #d1d5db !important;
    border-radius: 8px !important; color: #111827 !important; font-size: 0.84rem !important;
}
[data-testid="stWidgetLabel"] p { color: #374151 !important; font-size: 0.78rem !important; font-weight: 500 !important; }

/* ── Sidebar: New Document button styling ── */
[data-testid="stSidebar"] [data-testid="stButton"]:first-child button {
    background: rgba(255,255,255,0.09) !important;
    color: rgba(255,255,255,0.88) !important;
    border: 1px solid rgba(255,255,255,0.14) !important;
    border-radius: 8px !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    margin: 0.6rem 0.5rem 0.2rem !important;
    width: calc(100% - 1rem) !important;
}
[data-testid="stSidebar"] [data-testid="stButton"]:first-child button:hover {
    background: rgba(255,255,255,0.15) !important;
}
/* Hide doc history click-trigger buttons — clicks handled via HTML overlay */
[data-testid="stSidebar"] [data-testid="stButton"]:not(:first-child) button {
    visibility: hidden !important;
    height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    min-height: 0 !important;
    border: none !important;
    position: absolute !important;
}

/* ── Buttons ── */
[data-testid="stButton"] button,
[data-testid="stFormSubmitButton"] button {
    font-weight: 500 !important; border-radius: 8px !important;
    font-size: 0.83rem !important; transition: all 0.15s !important;
}
[data-testid="stButton"] button[kind="primary"],
[data-testid="stFormSubmitButton"] button {
    background: #4f6ef7 !important; color: #fff !important; border: none !important;
}
[data-testid="stButton"] button[kind="secondary"] {
    background: #f3f4f6 !important; color: #374151 !important;
    border: 1.5px solid #e5e7eb !important;
}
[data-testid="stAlert"] { border-radius: 9px !important; font-size: 0.81rem !important; }
[data-testid="stExpander"] { background: #f9fafb !important; border: 1px solid #e5e7eb !important; border-radius: 9px !important; }
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.15); border-radius: 4px; }

/* ══ SIDEBAR COMPONENT STYLES ══ */
.sb-wrap { display: flex; flex-direction: column; min-height: 100vh; padding-bottom: 1rem; }

.sb-brand {
    padding: 1.8rem 1.1rem 1rem;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    font-size: 1.2rem; font-weight: 700; color: #f9fafb;
    letter-spacing: -0.02em;
}
.sb-brand .ac { color: #818cf8; }

.sb-new-btn {
    margin: 0.75rem 0.9rem 0.5rem;
    display: block; text-align: center;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    color: rgba(255,255,255,0.85) !important;
    font-size: 0.81rem; font-weight: 500;
    cursor: pointer; text-decoration: none;
}

.sb-lbl {
    font-size: 0.57rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: rgba(255,255,255,0.22);
    padding: 1rem 1.1rem 0.4rem; display: block;
}

.sb-step {
    display: flex; align-items: center; gap: 0.7rem;
    padding: 0.55rem 1.1rem;
    border-left: 3px solid transparent;
    margin: 0;
}
.sb-step.active { background: rgba(99,102,241,0.15); border-left-color: #6366f1; }
.sb-step-num {
    width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.62rem; font-weight: 700;
    background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.3);
}
.sb-step.active .sb-step-num { background: #6366f1; color: #fff; }
.sb-step.done   .sb-step-num { background: #16a34a; color: #fff; font-size: 0.7rem; }
.sb-step-label { font-size: 0.81rem; font-weight: 500; color: rgba(255,255,255,0.3); }
.sb-step.active .sb-step-label { color: #c7d2fe; font-weight: 600; }
.sb-step.done   .sb-step-label { color: rgba(255,255,255,0.5); }

.sb-hr { height: 1px; background: rgba(255,255,255,0.07); margin: 0.6rem 1.1rem; }

.sb-doc {
    display: flex; align-items: flex-start; gap: 0.6rem;
    padding: 0.6rem 1.1rem; border-left: 3px solid transparent;
}
.sb-doc.active { background: rgba(99,102,241,0.15); border-left-color: #6366f1; }
.sb-doc-icon { font-size: 0.85rem; flex-shrink: 0; opacity: 0.5; margin-top: 0.1rem; }
.sb-doc-name { font-size: 0.78rem; font-weight: 500; color: rgba(255,255,255,0.6); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.4; }
.sb-doc.active .sb-doc-name { color: #c7d2fe; }
.sb-doc-meta { font-size: 0.65rem; color: rgba(255,255,255,0.25); margin-top: 0.1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.sb-footer { padding: 0 1.1rem 0.5rem; margin-top: auto; }
.api-pill { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.68rem; font-weight: 500; padding: 0.28rem 0.65rem; border-radius: 20px; }
.api-ok   { background: rgba(22,163,74,0.15); color: #4ade80; border: 1px solid rgba(22,163,74,0.3); }
.api-fail { background: rgba(220,38,38,0.15); color: #f87171; border: 1px solid rgba(220,38,38,0.3); }
.api-dot  { width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex-shrink: 0; }

/* ══ MAIN AREA ══ */
.page-title { font-size: 1.4rem; font-weight: 700; color: #111827; letter-spacing: -0.025em; margin-bottom: 0.25rem; }
.page-title .ac { color: #4f6ef7; }
.page-sub { font-size: 0.875rem; color: #6b7280; line-height: 1.65; margin-bottom: 1.5rem; }

.dept-tile { background: #fff; border: 1.5px solid #e5e7eb; border-radius: 12px; padding: 1.1rem 0.5rem; text-align: center; transition: all 0.12s; }
.dept-tile:hover { border-color: #a5b4fc; background: #eef2ff; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(79,110,247,0.12); }
.dt-icon { font-size: 1.55rem; line-height: 1; margin-bottom: 0.35rem; }
.dt-name { font-size: 0.74rem; font-weight: 600; color: #374151; line-height: 1.3; }

.tpl-row { display: flex; align-items: center; gap: 0.75rem; padding: 0.9rem 1.1rem; background: #fff; border: 1.5px solid #e5e7eb; border-radius: 10px; margin-bottom: 0.5rem; }
.tpl-row:hover { border-color: #a5b4fc; background: #f5f3ff; }
.tpl-name { font-size: 0.84rem; font-weight: 500; color: #1f2937; flex: 1; }

.sec-badge { display: inline-flex; align-items: center; font-size: 0.63rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; padding: 0.18rem 0.55rem; border-radius: 20px; margin-bottom: 0.45rem; }
.sbb { background: #eef2ff; color: #4f6ef7; }
.sbg { background: #f0fdf4; color: #16a34a; }
.sec-title { font-size: 1.1rem; font-weight: 700; color: #111827; margin-bottom: 0.5rem; line-height: 1.3; }
.prog-wrap { display: flex; align-items: center; gap: 0.65rem; margin-bottom: 1.35rem; }
.prog-bg   { flex: 1; height: 5px; background: #e5e7eb; border-radius: 5px; overflow: hidden; }
.prog-fill { height: 100%; background: linear-gradient(90deg,#4f6ef7,#818cf8); border-radius: 5px; }
.prog-txt  { font-size: 0.68rem; font-weight: 600; color: #9ca3af; white-space: nowrap; }
.q-num  { font-size: 0.63rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #4f6ef7; margin-bottom: 0.18rem; }
.q-text { font-size: 0.875rem; color: #374151; line-height: 1.6; margin-bottom: 0.35rem; }
.q-div  { height: 1px; background: #f3f4f6; margin: 0.85rem 0; }

.preview-outer { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; height: calc(100vh - 80px); }
.preview-hdr   { flex-shrink: 0; border-bottom: 1px solid #f3f4f6; padding: 0.85rem 1.4rem; }
.preview-hdr-lbl { font-size: 0.63rem; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; color: #9ca3af; }
.preview-body  { flex: 1; overflow-y: auto; padding: 1.25rem 1.4rem; }
.preview-empty { padding: 3rem 1rem; text-align: center; }
.preview-empty-icon { font-size: 2rem; opacity: 0.3; margin-bottom: 0.6rem; }
.preview-empty-txt  { font-size: 0.8rem; color: #d1d5db; font-style: italic; }
.psec { padding-bottom: 1.4rem; margin-bottom: 1.4rem; border-bottom: 1px solid #f3f4f6; }
.psec:last-child { border-bottom: none; padding-bottom: 0; margin-bottom: 0; }
.psec-hdr { display: flex; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.55rem; }
.psec-name { font-size: 0.86rem; font-weight: 600; color: #1f2937; line-height: 1.4; }
.chip { font-size: 0.58rem; font-weight: 700; text-transform: uppercase; padding: 0.14rem 0.48rem; border-radius: 20px; white-space: nowrap; flex-shrink: 0; }
.chip-a { background: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; }
.chip-g { background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }
.psec-body { font-size: 0.8rem; line-height: 1.85; color: #6b7280; white-space: pre-wrap; }
.cmp-title { font-size: 0.97rem; font-weight: 700; color: #1f2937; margin: 1.4rem 0 0.4rem; padding-bottom: 0.35rem; border-bottom: 1.5px solid #e5e7eb; }
.cmp-title:first-child { margin-top: 0; }
.cmp-body { font-size: 0.81rem; line-height: 1.85; color: #6b7280; white-space: pre-wrap; }

.done-banner { background: linear-gradient(135deg,#eef2ff,#f5f3ff); border: 1.5px solid #c7d2fe; border-radius: 12px; padding: 1.35rem 1.6rem; margin-bottom: 1.1rem; }
.done-title  { font-size: 1.05rem; font-weight: 700; color: #1f2937; margin-bottom: 0.18rem; }
.done-sub    { font-size: 0.8rem; color: #6b7280; }
.dl-btn { display: block; text-align: center; background: #4f6ef7; color: #fff !important; font-weight: 600; font-size: 0.83rem; padding: 0.6rem 1rem; border-radius: 8px; text-decoration: none !important; margin-bottom: 0.55rem; }

.doc-view-title { font-size: 1.35rem; font-weight: 700; color: #111827; letter-spacing: -0.02em; margin-bottom: 0.2rem; }
.doc-view-meta  { font-size: 0.78rem; color: #9ca3af; margin-bottom: 1.5rem; }
.doc-view-body  { background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 1.75rem 2rem; max-height: calc(100vh - 280px); overflow-y: auto; }
.doc-sec-title  { font-size: 1rem; font-weight: 700; color: #1f2937; margin: 1.5rem 0 0.4rem; padding-bottom: 0.35rem; border-bottom: 1.5px solid #e5e7eb; }
.doc-sec-title:first-child { margin-top: 0; }
.doc-sec-body   { font-size: 0.83rem; line-height: 1.9; color: #4b5563; white-space: pre-wrap; }

.ld-row { display: flex; align-items: center; gap: 0.5rem; color: #9ca3af; font-size: 0.81rem; padding: 1.25rem 0; }
.ld { width: 5px; height: 5px; border-radius: 50%; background: #4f6ef7; animation: pulse 1.2s ease infinite; }
.ld:nth-child(2){animation-delay:.2s;} .ld:nth-child(3){animation-delay:.4s;}
.fsec { font-size: 0.63rem; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; color: #9ca3af; padding: 0.65rem 0 0.4rem; border-top: 1px solid #f3f4f6; margin-top: 0.4rem; display: block; }
.fsec:first-of-type { border-top: none; padding-top: 0; margin-top: 0; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.2;} }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
DEPT_DISPLAY = {
    "dept_hr":                  ("👥","Human Resources"),
    "dept_finance":             ("💰","Finance"),
    "dept_product_management":  ("🗂️","Product Management"),
    "dept_engineering":         ("⚙️","Engineering"),
    "dept_qa":                  ("🔍","QA"),
    "dept_operations":          ("🔧","Operations"),
    "dept_support":             ("🎧","Support"),
    "dept_marketing":           ("📣","Marketing"),
    "dept_sales":               ("📈","Sales"),
    "dept_business_operations": ("🏢","Business Ops"),
    "dept_legal__compliance":   ("⚖️","Legal & Compliance"),
    "dept_it__security":         ("🖥️","IT & Security"),
    "dept_sales__marketing":     ("📊","Sales & Marketing"),
}
def dept_display(dept_id, raw_name=""):
    if dept_id in DEPT_DISPLAY: return DEPT_DISPLAY[dept_id]
    clean = raw_name.replace("_"," ").title() if raw_name else dept_id.replace("_"," ").title()
    return ("🏢", clean)

DEFAULTS = {
    "page":"home","dept_id":None,"dept_name":"","template_id":None,"template_name":"",
    "company_context":{},"session_id":None,"current_section":None,"current_index":0,
    "total_sections":0,"questions":[],"generated_content":None,"edited_content":"",
    "editing":False,"preview_sections":[],"all_done":False,"compiled_content":None,
    "document_id":None,"history":[],"need_fetch":True,"need_questions":False,
    "api_ok":None,"viewing_doc":None,
}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k] = v

# ─────────────────────────────────────────────────────────────
def api(method, path, **kwargs):
    try:
        r = getattr(requests, method)(f"{API_BASE}{path}", timeout=90, **kwargs)
        r.raise_for_status()
        st.session_state.api_ok = True
        return r.json(), None
    except requests.exceptions.ConnectionError:
        st.session_state.api_ok = False
        return None, "Cannot connect — run: `uvicorn app.main:app --reload`"
    except requests.exceptions.HTTPError as e:
        try:    d = e.response.json().get("detail", str(e))
        except: d = str(e)
        return None, d
    except Exception as e: return None, str(e)

def ping():
    try:
        r = requests.get(f"{API_BASE}/docs", timeout=3)
        st.session_state.api_ok = r.status_code < 500
    except: st.session_state.api_ok = False

def reset():
    hist = st.session_state.history
    for k,v in DEFAULTS.items(): st.session_state[k] = v
    st.session_state.history = hist

def upsert_preview(sid, title, content, status):
    for s in st.session_state.preview_sections:
        if s["section_id"] == sid:
            s["content"]=content; s["status"]=status; return
    st.session_state.preview_sections.append(
        {"section_id":sid,"section_title":title,"content":content,"status":status})

def do_approve(sec_id, edited):
    sess = st.session_state.session_id
    with st.spinner("Approving..."):
        data, err = api("post", f"/sessions/{sess}/approve_section",
                        json={"section_id":sec_id,"edited_content":edited})
    if err: st.error(err); return
    final = edited if edited else st.session_state.generated_content
    upsert_preview(sec_id, st.session_state.current_section.get("title",sec_id), final, "approved")
    st.session_state.all_done = data.get("all_sections_done", False)
    if not st.session_state.all_done: st.session_state.need_fetch = True
    st.session_state.editing = False
    st.rerun()

def add_to_history(session_id, doc_name, dept_name, compiled=False, content=""):
    for h in st.session_state.history:
        if h["session_id"] == session_id:
            if compiled: h["compiled"]=True
            if content:  h["content"]=content
            return
    st.session_state.history.insert(0,{
        "session_id":session_id,"doc_name":doc_name[:32],"dept_name":dept_name,
        "created_at":datetime.now().strftime("%b %d, %H:%M"),"compiled":compiled,"content":content,
    })

if st.session_state.api_ok is None: ping()

# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        page     = st.session_state.page
        compiled = [h for h in st.session_state.history if h.get("compiled")]
        in_prog  = [h for h in st.session_state.history if not h.get("compiled")]
        api_cls  = "api-pill api-ok" if st.session_state.api_ok else "api-pill api-fail"
        api_txt  = "API connected"   if st.session_state.api_ok else "API offline"

        steps = [
            (1,"Department",   page=="home" and not st.session_state.dept_id,   st.session_state.dept_id is not None),
            (2,"Template",     page=="home" and bool(st.session_state.dept_id),  st.session_state.template_id is not None),
            (3,"Company Info", page=="context",                                  page in ("generating","view_doc")),
            (4,"Generate",     page in ("generating","view_doc"),                False),
        ]

        # ── Brand title (pure HTML, no widget — renders immediately) ──
        st.markdown('<div class="sb-brand">📋 Doc<span class="ac">Forge</span></div>',
                    unsafe_allow_html=True)

        # ── New Document button — right after brand ──
        if st.button("＋  New Document", key="sb_new", use_container_width=True):
            reset(); st.session_state.viewing_doc = None; st.rerun()

        # ── Doc history click buttons (hidden, just for interactivity) ──
        for doc in compiled[:8]:
            if st.button(f"open_{doc['session_id']}", key=f"h_{doc['session_id']}",
                         use_container_width=True):
                st.session_state.viewing_doc = doc
                st.session_state.page = "view_doc"
                st.rerun()

        # ── Rest of sidebar as one HTML block ──
        h  = '<div class="sb-lbl">Current Session</div>'
        for num, label, is_active, is_done in steps:
            cls  = "sb-step active" if is_active else ("sb-step done" if is_done else "sb-step")
            tick = "✓" if is_done else str(num)
            h += (f'<div class="{cls}">'
                  f'<div class="sb-step-num">{tick}</div>'
                  f'<div class="sb-step-label">{label}</div>'
                  f'</div>')

        if compiled:
            h += '<div class="sb-hr"></div>'
            h += '<div class="sb-lbl">Generated Docs</div>'
            for doc in compiled[:8]:
                is_cur = (st.session_state.viewing_doc and
                          st.session_state.viewing_doc.get("session_id") == doc["session_id"])
                dc = "sb-doc active" if is_cur else "sb-doc"
                h += (f'<div class="{dc}">'
                      f'<span class="sb-doc-icon">📄</span>'
                      f'<div style="min-width:0">'
                      f'<div class="sb-doc-name">{doc["doc_name"]}</div>'
                      f'<div class="sb-doc-meta">{doc.get("dept_name","")} · {doc.get("created_at","")}</div>'
                      f'</div></div>')

        if in_prog:
            h += '<div class="sb-hr"></div>'
            h += '<div class="sb-lbl">In Progress</div>'
            for doc in in_prog[:4]:
                h += (f'<div class="sb-doc">'
                      f'<span class="sb-doc-icon">✏️</span>'
                      f'<div style="min-width:0">'
                      f'<div class="sb-doc-name">{doc["doc_name"]}</div>'
                      f'<div class="sb-doc-meta">{doc.get("dept_name","")} · {doc.get("created_at","")}</div>'
                      f'</div></div>')

        h += (f'<div style="flex:1"></div>'
              f'<div class="sb-footer">'
              f'<div class="sb-hr" style="margin:0 0 0.6rem;"></div>'
              f'<div class="{api_cls}"><span class="api-dot"></span>{api_txt}</div>'
              f'</div>'
              f'</div>')

        st.markdown(h, unsafe_allow_html=True)

render_sidebar()

# ─────────────────────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────────────────────
def page_view_doc():
    doc = st.session_state.viewing_doc
    if not doc: st.session_state.page="home"; st.rerun()
    sess    = doc["session_id"]
    content = doc.get("content","")
    if not content:
        with st.spinner("Loading..."):
            data, err = api("get", f"/sessions/{sess}/sections")
        if err: st.error(err); return
        parts   = [f"## {s['section_title']}\n\n{s['content']}" for s in data.get("sections",[])]
        content = "\n\n---\n\n".join(parts)
        for h in st.session_state.history:
            if h["session_id"]==sess: h["content"]=content

    if st.button("← Back", key="back_view", type="secondary"):
        st.session_state.viewing_doc=None; st.session_state.page="home"; st.rerun()

    st.markdown(f'<div class="doc-view-title">{doc["doc_name"]}</div>'
                f'<div class="doc-view-meta">{doc.get("dept_name","")} · {doc.get("created_at","")}</div>',
                unsafe_allow_html=True)
    c1,c2,_ = st.columns([2,2,6], gap="small")
    with c1:
        st.markdown(f'<a class="dl-btn" href="{API_BASE}/sessions/{sess}/download_pdf" target="_blank">⬇  Download PDF</a>',
                    unsafe_allow_html=True)
    with c2:
        if st.button("📤  Publish to Notion", key="btn_notion_view"):
            st.session_state["show_notion_view"] = not st.session_state.get("show_notion_view",False); st.rerun()
    if st.session_state.get("show_notion_view"):
        n1,n2,n3 = st.columns([4,1,1], gap="small")
        with n1: nid = st.text_input("Notion Database ID", key="nid_view", placeholder="Paste Notion DB ID...")
        with n2:
            st.markdown("<div style='margin-top:1.7rem'>", unsafe_allow_html=True)
            if st.button("Publish", type="primary", key="btn_notion_go"):
                with st.spinner("Publishing..."):
                    _, err = api("post", f"/sessions/{sess}/publish_notion",
                                 json={"notion_database_id":nid.strip(),"doc_title":doc["doc_name"]})
                if err: st.error(err)
                else: st.success("Published ✓"); st.session_state["show_notion_view"]=False
            st.markdown("</div>", unsafe_allow_html=True)
        with n3:
            st.markdown("<div style='margin-top:1.7rem'>", unsafe_allow_html=True)
            if st.button("Cancel", type="secondary", key="btn_notion_cancel"):
                st.session_state["show_notion_view"]=False; st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="doc-view-body">', unsafe_allow_html=True)
    for block in content.split("\n\n---\n\n"):
        lines = block.strip().split("\n", 1)
        title = lines[0].replace("## ", "")
        body  = lines[1].strip() if len(lines) > 1 else ""
        html  = render_markdown(body)
        st.markdown(
            f'<div class="doc-sec-title">{title}</div>'
            f'<div class="doc-sec-body">{html}</div>',
            unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

def page_home():
    if not st.session_state.dept_id:
        st.markdown('<div class="page-title">Select a <span class="ac">Department</span></div>'
                    '<div class="page-sub">Choose the department this document belongs to.</div>',
                    unsafe_allow_html=True)
        data, err = api("get", "/departments/")
        depts = data if (data and not err) else [{"dept_id":k,"dept_name":v[1]} for k,v in DEPT_DISPLAY.items()]
        cols = st.columns(5, gap="small")
        for i, dept in enumerate(depts):
            did=dept.get("dept_id",""); raw=dept.get("dept_name",did)
            icon, name = dept_display(did, raw)
            with cols[i%5]:
                st.markdown(f'<div class="dept-tile"><div class="dt-icon">{icon}</div>'
                            f'<div class="dt-name">{name}</div></div>', unsafe_allow_html=True)
                if st.button("Select", key=f"d_{did}", use_container_width=True):
                    st.session_state.dept_id=did; st.session_state.dept_name=name; st.rerun()
    else:
        did=st.session_state.dept_id; name=st.session_state.dept_name; icon=dept_display(did)[0]
        if st.button("← Back to Departments", key="back_dept", type="secondary"):
            st.session_state.dept_id=None; st.session_state.dept_name=""; st.rerun()
        st.markdown(f'<div class="page-title" style="margin-top:.5rem;">{icon} {name} <span class="ac">Templates</span></div>'
                    f'<div class="page-sub">Select a document template to generate.</div>', unsafe_allow_html=True)
        data, err = api("get", f"/templates/?dept_id={did}")
        if err: st.error(err); return
        if not data: st.info(f"No templates for {name}."); return
        for tpl in data:
            tpl_id=tpl.get("id") or tpl.get("_id",""); tpl_name=tpl.get("label") or tpl.get("doc_name",tpl_id)
            c1,c2 = st.columns([7,1], gap="small")
            with c1:
                st.markdown(f'<div class="tpl-row"><span style="font-size:.95rem;margin-right:.3rem;">📄</span>'
                            f'<span class="tpl-name">{tpl_name}</span></div>', unsafe_allow_html=True)
            with c2:
                if st.button("Select", key=f"t_{tpl_id}", type="primary", use_container_width=True):
                    st.session_state.template_id=tpl_id; st.session_state.template_name=tpl_name
                    st.session_state.page="context"; st.rerun()

def page_context():
    if st.button("← Back", key="back_ctx", type="secondary"):
        st.session_state.page="home"; st.rerun()
    st.markdown(f'<div class="page-title" style="margin-top:.5rem;">Company <span class="ac">Context</span></div>'
                f'<div class="page-sub">7 quick fields so DocForge generates accurate content for <strong>{st.session_state.template_name}</strong>.</div>',
                unsafe_allow_html=True)
    with st.form("ctx_form"):
        c1,c2 = st.columns(2, gap="large")
        with c1:
            st.markdown('<span class="fsec">Your Company</span>', unsafe_allow_html=True)
            company_name    = st.text_input("Company Name *", placeholder="e.g. Acme Inc.")
            industry        = st.selectbox("Industry *", ["HR Tech","FinTech","DevTools","MarTech","HealthTech","EdTech","LegalTech","PropTech","E-commerce","Cybersecurity","Data & Analytics","CRM / Sales","IT Operations","Other SaaS"])
            company_stage   = st.selectbox("Company Stage *", ["Early Stage / Startup","Growth Stage","Scale-up","Enterprise"])
            target_customer = st.selectbox("Primary Customer *", ["SMBs","Mid-market","Enterprise","Developers","Consumers (B2C)","Agencies","Mixed"])
        with c2:
            st.markdown('<span class="fsec">Your Product</span>', unsafe_allow_html=True)
            product_name = st.text_input("Product Name *", placeholder="e.g. AcmePay")
            product_desc = st.text_area("What does your product do? *", placeholder="Core functionality, who it's for, key value.", height=108)
            key_problem  = st.text_area("Key Problem You Solve *", placeholder="What pain point does your product eliminate?", height=80)
        submitted = st.form_submit_button("Start Generating →", use_container_width=True)
    if submitted:
        missing=[n for n,v in [("Company Name",company_name),("Product Name",product_name),
                                ("Product Description",product_desc),("Key Problem",key_problem)] if not v.strip()]
        if missing: st.error(f"Please fill in: {', '.join(missing)}"); return
        st.session_state.company_context = {
            "company_name":company_name.strip(),"product_name":product_name.strip(),
            "product_description":product_desc.strip(),"industry_vertical":industry,
            "company_stage":company_stage,"target_customer":target_customer,
            "key_problem_solved":key_problem.strip(),
        }
        with st.spinner("Creating session..."):
            data, err = api("post", "/sessions/", json={"template_id":st.session_state.template_id})
        if err: st.error(err); return
        st.session_state.session_id=data["session_id"]; st.session_state.total_sections=data["total_sections"]
        add_to_history(data["session_id"], st.session_state.template_name, st.session_state.dept_name)
        st.session_state.page="generating"; st.session_state.need_fetch=True; st.rerun()

def page_generating():
    sess = st.session_state.session_id
    if st.session_state.need_fetch and not st.session_state.all_done:
        data, err = api("get", f"/sessions/{sess}/current_section")
        if err: st.error(err); return
        if data.get("all_sections_done"):
            st.session_state.all_done=True; st.session_state.need_fetch=False
        else:
            st.session_state.current_section=data["section"]; st.session_state.current_index=data["current_index"]
            st.session_state.total_sections=data["total_sections"]; st.session_state.questions=[]
            st.session_state.generated_content=None; st.session_state.edited_content=""
            st.session_state.editing=False; st.session_state.need_fetch=False; st.session_state.need_questions=True

    if st.session_state.need_questions and not st.session_state.all_done:
        sec_id = st.session_state.current_section["id"]
        with st.spinner("Generating questions..."):
            data, err = api("post", f"/sessions/{sess}/generate_questions",
                            json={"section_id":sec_id,"company_context":st.session_state.company_context})
        if err: st.error(err); return
        st.session_state.questions=data.get("questions",[]); st.session_state.need_questions=False; st.rerun()

    left, right = st.columns([9,11], gap="large")
    with left:
        if st.session_state.all_done: _done_left()
        elif not st.session_state.questions:
            st.markdown('<div class="ld-row"><span class="ld"></span><span class="ld"></span><span class="ld"></span><span>Generating questions...</span></div>', unsafe_allow_html=True)
        elif st.session_state.generated_content is not None: _approve_panel()
        else: _questions_form()
    with right: _preview_panel()

def _questions_form():
    sess=st.session_state.session_id; section=st.session_state.current_section
    sec_id=section["id"]; idx=st.session_state.current_index; total=st.session_state.total_sections
    pct=int((idx/total)*100) if total else 0
    st.markdown(f'<div class="sec-badge sbb">Section {idx+1} of {total}</div>'
                f'<div class="sec-title">{section.get("title","")}</div>'
                f'<div class="prog-wrap"><div class="prog-bg"><div class="prog-fill" style="width:{pct}%"></div></div>'
                f'<div class="prog-txt">{pct}% complete</div></div>', unsafe_allow_html=True)
    with st.form(f"qf_{sec_id}"):
        for i,q in enumerate(st.session_state.questions):
            st.markdown(f'<div class="q-num">Q{i+1}</div><div class="q-text">{q["question_text"]}</div>', unsafe_allow_html=True)
            st.text_area("", key=f"ta_{q['question_id']}", placeholder="Your answer...", height=72, label_visibility="collapsed")
            if i < len(st.session_state.questions)-1:
                st.markdown('<div class="q-div"></div>', unsafe_allow_html=True)
        submitted = st.form_submit_button("Generate Section →", use_container_width=True)
    if submitted:
        payload=[{"question_id":q["question_id"],"answer":st.session_state.get(f"ta_{q['question_id']}","")}
                 for q in st.session_state.questions]
        with st.spinner("Saving answers..."):
            _, err = api("post", f"/sessions/{sess}/submit_answers", json={"section_id":sec_id,"answers":payload})
        if err: st.error(err); return
        with st.spinner("Writing section with AI..."):
            data, err = api("post", f"/sessions/{sess}/generate_section",
                            json={"section_id":sec_id,"company_context":st.session_state.company_context})
        if err: st.error(err); return
        content=data.get("content",""); st.session_state.generated_content=content; st.session_state.edited_content=content
        upsert_preview(sec_id, section.get("title",sec_id), content, "generated"); st.rerun()

def _approve_panel():
    section=st.session_state.current_section; sec_id=section["id"]
    idx=st.session_state.current_index; total=st.session_state.total_sections
    pct=int((idx/total)*100) if total else 0
    st.markdown(f'<div class="sec-badge sbg">✓ Generated</div>'
                f'<div class="sec-title">{section.get("title","")}</div>'
                f'<div class="prog-wrap"><div class="prog-bg"><div class="prog-fill" style="width:{pct}%"></div></div>'
                f'<div class="prog-txt">{pct}% complete</div></div>'
                f'<div style="font-size:.79rem;color:#9ca3af;margin-bottom:.9rem;">Review in preview → Edit or approve to continue.</div>',
                unsafe_allow_html=True)
    if st.session_state.editing:
        new_val = st.text_area("", value=st.session_state.edited_content, height=300, key="edit_ta", label_visibility="collapsed")
        st.session_state.edited_content = new_val
        c1,c2=st.columns(2,gap="small")
        with c1:
            if st.button("✕  Cancel", use_container_width=True, type="secondary", key="btn_cancel"):
                st.session_state.editing=False; st.session_state.edited_content=st.session_state.generated_content; st.rerun()
        with c2:
            if st.button("✓  Save & Approve", use_container_width=True, type="primary", key="btn_save"):
                do_approve(sec_id, st.session_state.edited_content)
    else:
        c1,c2=st.columns(2,gap="small")
        with c1:
            if st.button("✎  Edit", use_container_width=True, type="secondary", key="btn_edit"):
                st.session_state.editing=True; st.rerun()
        with c2:
            if st.button("✓  Approve →", use_container_width=True, type="primary", key="btn_approve"):
                do_approve(sec_id, None)

def _done_left():
    sess=st.session_state.session_id
    st.markdown('<div class="done-banner"><div class="done-title">🎉 All sections complete!</div>'
                '<div class="done-sub">Review the document in the preview, then compile and download.</div></div>',
                unsafe_allow_html=True)
    if not st.session_state.compiled_content:
        if st.button("Compile Document →", use_container_width=True, type="primary", key="btn_compile"):
            with st.spinner("Compiling..."): data, err = api("post", f"/sessions/{sess}/compile")
            if err: st.error(err); return
            st.session_state.document_id=data["document_id"]
            sec_data, _ = api("get", f"/sessions/{sess}/sections")
            if sec_data:
                parts=[f"## {s['section_title']}\n\n{s['content']}" for s in sec_data.get("sections",[])]
                compiled="\n\n---\n\n".join(parts); st.session_state.compiled_content=compiled
                add_to_history(sess, st.session_state.template_name, st.session_state.dept_name, compiled=True, content=compiled)
            st.rerun()
    else:
        st.success("Document compiled ✓")
        st.markdown(f'<a class="dl-btn" href="{API_BASE}/sessions/{sess}/download_pdf" target="_blank">⬇  Download PDF</a>',
                    unsafe_allow_html=True)
        with st.expander("📤 Publish to Notion"):
            nid=st.text_input("Notion Database ID", key="nid", placeholder="Paste your Notion database ID...")
            if st.button("Publish →", use_container_width=True, key="btn_notion"):
                if not nid.strip(): st.warning("Enter a Notion Database ID first.")
                else:
                    with st.spinner("Publishing..."):
                        _, err=api("post", f"/sessions/{sess}/publish_notion",
                                   json={"notion_database_id":nid.strip(),"doc_title":st.session_state.template_name})
                    if err: st.error(err)
                    else: st.success("Published to Notion ✓")

def render_markdown(text: str) -> str:
    """Convert markdown to HTML for safe rendering in preview."""
    return md_lib.markdown(text, extensions=["tables", "nl2br", "sane_lists"])

def _preview_panel():
    # Build entire preview as ONE html string — prevents Streamlit from
    # breaking open divs by injecting widgets between separate st.markdown() calls
    inner = ""

    if st.session_state.compiled_content:
        for block in st.session_state.compiled_content.split("\n\n---\n\n"):
            lines = block.strip().split("\n", 1)
            title = lines[0].replace("## ", "")
            body  = lines[1].strip() if len(lines) > 1 else ""
            inner += (f'<div class="cmp-title">{title}</div>'
                      f'<div class="cmp-body">{render_markdown(body)}</div>')

    elif st.session_state.preview_sections:
        for s in st.session_state.preview_sections:
            chip  = ('<span class="chip chip-a">✓ approved</span>' if s["status"] == "approved"
                     else '<span class="chip chip-g">● generated</span>')
            inner += (f'<div class="psec">'
                      f'<div class="psec-hdr"><div class="psec-name">{s["section_title"]}</div>{chip}</div>'
                      f'<div class="psec-body">{render_markdown(s.get("content",""))}</div>'
                      f'</div>')
    else:
        inner = ('<div class="preview-empty">'
                 '<div class="preview-empty-icon">📝</div>'
                 '<div class="preview-empty-txt">Approved sections will appear here</div>'
                 '</div>')

    st.markdown(
        f'<div class="preview-outer">'
        f'<div class="preview-hdr"><div class="preview-hdr-lbl">📄 Document Preview</div></div>'
        f'<div class="preview-body">{inner}</div>'
        f'</div>',
        unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
if st.session_state.page == "home":         page_home()
elif st.session_state.page == "context":    page_context()
elif st.session_state.page == "generating": page_generating()
elif st.session_state.page == "view_doc":   page_view_doc()