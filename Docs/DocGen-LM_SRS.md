# 📄 System Requirements Specification

**Project Name**: `DocGen-LM`  
**Purpose**: Generate detailed, readable HTML documentation for Python and MATLAB codebases using static analysis and a required local LLM (via LMStudio). The tool is implemented entirely in Python.

---

## 1. 📌 Introduction

### 1.1 Purpose
This tool produces human-readable documentation for codebases written in Python and MATLAB. It extracts the structure of the code using static analysis and generates detailed descriptions using a local LLM. The documentation is rendered as a set of navigable HTML pages for desktop viewing.

### 1.2 Scope
- Run from the command line:
  ```bash
  python docgenerator.py /path/to/codebase --format html --output ./docs
  ```
- Analyze `.py` and `.m` files
- Use a local LLM (via LMStudio) to generate all summaries and explanations
- Generate HTML output only
- For desktop use (no mobile support)

### 1.3 Intended Users
- Developers and maintainers of Python or MATLAB projects  
- Documentation authors  
- Users of local LLMs (e.g. LMStudio)

---

## 2. ⚙️ Functional Requirements

### 2.1 Code Scanning
- Recursively scan a specified directory
- Identify `.py` (Python) and `.m` (MATLAB) files
- Allow exclusion of files or folders via `--ignore`
- Automatically skip directories named `.git`

### 2.2 Language-Specific Parsing

#### 2.2.1 Python
- Use the built-in `ast` module to extract:
  - File docstrings
  - Classes and functions
  - Function signatures and return annotations

#### 2.2.2 MATLAB
- Use simple line-based parsing to identify:
  - Function definitions
  - Argument lists
  - File-level comments

> Note: MATLAB code is not executed or interpreted

### 2.3 LLM-Powered Summary (Required)
- All descriptions must be generated using an LLM via LMStudio
- The tool must not operate without a working LLM backend
- Use the LLM to summarize:
  - Overall project purpose
  - Each file/module
  - Each class and function
- Summaries must be clear, concise, and human-readable
- Use caching to avoid re-querying unchanged code

### 2.4 HTML Documentation Output

#### 2.4.1 Output Files
- `index.html`: project-level summary
- One HTML file per directory/module

#### 2.4.2 Content per Page
Each HTML page includes:
- LLM-generated summary of the file/module
- Documented classes and functions:
  - Signature
  - Description
  - Optional code block

#### 2.4.3 Navigation and Layout
- Static sidebar linking to all generated pages
- Basic anchor links for classes and functions
- No mobile layout or responsiveness required
- No third-party JS or CSS frameworks
- All layout and interaction must remain simple and minimal

---

## 3. 🧱 System Modules

| File               | Responsibility                        |
|--------------------|----------------------------------------|
| `docgenerator.py`  | CLI runner                             |
| `scanner.py`       | Discover source files                  |
| `parser_python.py` | Parse `.py` files                      |
| `parser_matlab.py` | Parse `.m` files                       |
| `llm_client.py`    | Interface with LMStudio                |
| `html_writer.py`   | Render output from templates           |
| `template.html`    | Shared Jinja2 layout                   |
| `cache.py`         | Cache LLM responses                    |

---

## 4. 💡 Non-Functional Requirements

- Written entirely in Python
- Python 3.9+
- Must use a running LMStudio or compatible local LLM API
- Works offline except for LLM queries
- Only basic dependencies: `requests`, `jinja2`, `pygments`

---

## 5. 📁 Output Example

```
/docs/
├── index.html
├── models.html
├── utils.html
├── control_systems.html
└── static/
    └── style.css
```

---

## 6. 🧠 HTML Layout Summary

- Top-level summary (`<h1>`) with LLM-generated text
- Subsections for classes and functions (`<h2>` / `<h3>`)
- `<pre>` blocks for optional source code display
- Sidebar with static links

---

## 7. 🧪 CLI Usage

```bash
python docgenerator.py ./my_project --output ./docs
```

Required flags:

| Flag       | Description                      |
|------------|----------------------------------|
| `--output` | Output directory for HTML files  |
| `--ignore` | Paths to skip                    |

The LLM must be running and reachable via `llm_client.py`.

---

## 8. 🚫 Explicit Exclusions

- No mobile layout
- No JS frameworks
- No runtime execution of code
- No visual diagrams
- No fallback documentation mode without LLM

---

## ✅ Summary for Codex

> Build a Python tool that reads `.py` and `.m` files, extracts code structure, sends each file/class/function to a local LLM for summarization, and writes a set of static HTML pages. The LLM is required. Keep layout and interactivity minimal and avoid mobile support or JS libraries.
