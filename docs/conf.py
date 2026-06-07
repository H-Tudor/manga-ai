# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

from __future__ import annotations

import sys
from pathlib import Path

# -- Path setup --------------------------------------------------------------
# Add all package src directories so autodoc can import the modules.
_root = Path(__file__).resolve().parents[1]
for _pkg in ("ai_translate", "manga_dex", "api"):
    sys.path.insert(0, str(_root / "packages" / _pkg / "src"))

# -- Project information -----------------------------------------------------
project = "Manga AI"
copyright = "2024, H-Tudor"
author = "H-Tudor"
release = "0.1.0"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",       # auto-generate docs from docstrings
    "sphinx.ext.napoleon",      # Google / NumPy style docstrings
    "sphinx.ext.viewcode",      # add links to highlighted source code
    "sphinx.ext.intersphinx",   # cross-links to external docs (Python, etc.)
    "sphinx.ext.autosummary",   # generate summary tables
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Autodoc options ---------------------------------------------------------
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "special-members": "__init__",
}
autodoc_typehints = "description"
autosummary_generate = True

# -- Napoleon settings -------------------------------------------------------
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_attr_annotations = True

# -- Intersphinx mapping -----------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest", None),
}

# -- Options for HTML output -------------------------------------------------
html_theme = "alabaster"
html_static_path = []
html_theme_options = {
    "description": "AI-powered manga translation platform",
    "github_user": "H-Tudor",
    "github_repo": "manga-ai",
    "github_banner": True,
    "fixed_sidebar": True,
}
