"""Security allowlists for generated AetherViz HTML."""

from __future__ import annotations

import re

ALLOWED_EXTERNAL_URLS = {
    "https://cdn.tailwindcss.com",
    "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css",
    "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js",
    "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js",
    "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.css",
    "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js",
    "https://cdn.staticfile.net/KaTeX/0.16.9/contrib/auto-render.min.js",
    "https://d3js.org/d3.v7.min.js",
    "https://cdn.staticfile.net/d3/7.9.0/d3.min.js",
}

KATEX_URL_PATTERN = re.compile(
    r"^https://(?:cdn\.jsdelivr\.net/npm/katex@[^/]+/dist|cdn\.staticfile\.net/KaTeX/[^/]+)/(katex\.min\.css|katex\.min\.js|contrib/auto-render\.min\.js)$"
)
