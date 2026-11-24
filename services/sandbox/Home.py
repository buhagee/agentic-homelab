"""System-managed Home page for the sandbox."""
from __future__ import annotations

import ast
import html
import re
from pathlib import Path

import streamlit as st

PAGES_DIR = Path(__file__).parent / "pages"

st.set_page_config(
    page_title="Sandbox",
    page_icon="🧰",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --sandbox-muted: rgba(128, 128, 128, .9);
        --sandbox-line: rgba(128, 128, 128, .28);
        --sandbox-accent: #7189e8;
    }
    .block-container { max-width: 1180px; padding: 2.4rem 3rem 4rem; }
    .hero {
        background: linear-gradient(135deg, #172033 0%, #26385c 62%, #4569d4 100%);
        border-radius: 24px;
        padding: 2.6rem 2.8rem;
        margin-bottom: 1.8rem;
        box-shadow: 0 18px 42px rgba(23,32,51,.18);
    }
    .hero-eyebrow { color: #b8c9ef; font-size: .76rem; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; }
    .hero-title { color: #fff; font-size: clamp(2.2rem, 5vw, 3.8rem); font-weight: 750; letter-spacing: -.045em; line-height: 1; margin: .7rem 0 1rem; }
    .hero-copy { color: #dfe8fb; font-size: 1.05rem; line-height: 1.6; max-width: 650px; margin: 0; }
    .hero-badge { display: inline-block; margin-top: 1.5rem; padding: .42rem .75rem; border: 1px solid rgba(255,255,255,.22); border-radius: 999px; color: #eef4ff; background: rgba(255,255,255,.1); font-size: .82rem; }
    .section-heading { font-size: 1.35rem; font-weight: 700; letter-spacing: -.02em; margin: 1.8rem 0 .85rem; }
    div[data-testid="stButton"] > button {
        background: transparent;
        border: 1px solid var(--sandbox-line);
        border-radius: 18px;
        min-height: 145px;
        padding: 1.25rem 1.3rem;
        text-align: left;
        transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
        white-space: pre-wrap;
        width: 100%;
    }
    div[data-testid="stButton"] > button:hover {
        border-color: var(--sandbox-accent);
        box-shadow: 0 10px 24px rgba(23,32,51,.12);
        transform: translateY(-2px);
    }
    div[data-testid="stButton"] > button p { color: inherit; line-height: 1.45; text-align: left; }
    .footer-note { opacity: .72; font-size: .82rem; text-align: center; margin-top: 2.3rem; }
    @media (max-width: 720px) {
        .block-container { padding: 1.2rem .9rem 2.5rem; }
        .hero { border-radius: 18px; padding: 1.7rem 1.35rem; }
        .hero-title { font-size: 2.45rem; }
        .hero-copy { font-size: .98rem; }
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: .75rem !important; }
        div[data-testid="column"] { flex: 1 1 100% !important; min-width: 100% !important; width: 100% !important; }
        div[data-testid="stButton"] > button { min-height: 118px; padding: 1rem 1.1rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def page_details(path: Path) -> tuple[str, str]:
    """Return display title and description without importing page code."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstring = ast.get_docstring(tree) or ""
    except (OSError, SyntaxError):
        docstring = ""

    title = docstring.splitlines()[0].strip() if docstring else ""
    if not title:
        title = re.sub(r"^\d+[_-]*", "", path.stem).replace("_", " ").replace("-", " ").title()
    description = " ".join(line.strip() for line in docstring.splitlines()[1:]).strip()
    return title, description


st.markdown(
        """
        <section class="hero">
            <div class="hero-eyebrow">Personal web workspace</div>
            <div class="hero-title">Sandbox</div>
            <p class="hero-copy">A focused home for dashboards, reports, visualisations, documents, and interactive tools.</p>
            <span class="hero-badge">● Ready · isolated runtime</span>
        </section>
        """,
        unsafe_allow_html=True,
)

st.markdown('<div class="section-heading">Your workspace</div>', unsafe_allow_html=True)

pages = sorted(
    path
    for path in PAGES_DIR.glob("*.py")
    if path.name != "__init__.py" and not path.name.startswith("_")
)
if not pages:
    st.info("No workspace pages yet. Add a Python file under `pages/` to get started.")
else:
    columns = st.columns(min(3, len(pages)))
    for index, page in enumerate(pages):
        title, description = page_details(page)
        safe_title = html.escape(title)
        safe_description = html.escape(description or "Interactive workspace tool.")
        with columns[index % len(columns)]:
            if st.button(
                f"**{safe_title}**\n\n{safe_description}",
                key=f"open_{page.name}",
                icon="➡️",
                width="stretch",
                help=f"Open {title}",
            ):
                st.switch_page(f"pages/{page.name}")

with st.expander("How pages are added"):
    st.write("Create a Python file under `pages/`. Streamlit discovers it automatically, and this Home page lists it on reload.")

st.markdown(
    '<div class="footer-note">Sandbox code runs in an isolated, resource-limited container. Keep secrets out of the workspace.</div>',
    unsafe_allow_html=True,
)
