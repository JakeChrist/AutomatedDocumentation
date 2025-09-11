# DocGen-LM

DocGen-LM generates static HTML documentation for Python, MATLAB, C++, and Java projects by analyzing source files and summarizing them with a local LLM. It now captures and renders **nested functions** and **subclasses**, so complex structures appear in the output as expandable sections.

## Prerequisites

- Python 3.9+
- LMStudio (or another compatible local LLM server)

## Installation

Clone the repository and install the required packages:

```bash
pip install -r requirements.txt
```

The tool depends on `requests`, `pygments`, `beautifulsoup4`, and `tqdm`.
Progress bars powered by `tqdm` are always displayed. It uses the
real `requests` library to communicate with LMStudio. Install
`tiktoken` for accurate token counting as listed in `requirements.txt`.
For the `explaincode` summary utility, additional packages
`markdown`, `python-docx`, and `reportlab` are required.

## CLI Usage

```bash
python docgenerator.py ./my_project --output ./docs
```

Required flags:

| Flag       | Description                      |
|------------|----------------------------------|
| `--output` | Output directory for HTML files  |
| `--ignore` | Paths to skip                    |

Directories named `.git` are ignored automatically.

Optional flags:

| Flag          | Description                      |
|---------------|----------------------------------|
| `--llm-url`   | Base URL of the LLM server       |
| `--model`     | Model name to use                |
| `--max-context-tokens` | Override the model's context window |
| `--chunk-token-budget` | Limit tokens per chunk (default 75% of context) |
| `--resume`    | Continue from cached progress (default clears progress) |
| `--clear-progress` | Remove saved progress after a run |

The LLM must be running and reachable via `llm_client.py`.

Reduce `--chunk-token-budget` when using models with very small context
windows to keep chunks well within the limit and avoid prompt leakage.

### Automatic Progress Saving

DocGen-LM stores intermediate results in a `cache.json` file inside the
output directory. Cached progress is cleared at startup unless `--resume`
is supplied. If the generator stops partway through, rerun it with
`--resume` to continue from the last saved point. Use `--clear-progress`
to remove the saved state after a successful run when resuming.
In the GUI, click **Resume DocGen** to continue using the cached progress.

Example of resuming an interrupted run:

```bash
python docgenerator.py ./my_project --output ./docs
# ... interrupted ...
python docgenerator.py ./my_project --output ./docs --resume
```

To rebuild from scratch, simply run without `--resume` (the default) or
delete `cache.json` manually. To drop progress after a resumed run, use
`--clear-progress`:

```bash
python docgenerator.py ./my_project --output ./docs --resume --clear-progress
```

### C++ Example

Given a simple C++ file `adder.cpp`:

```cpp
// Adds two integers
int add(int a, int b) {
    return a + b;
}
```

Generate documentation with:

```bash
python docgenerator.py ./cpp_project --output ./docs
```

DocGen-LM identifies the `add` function and renders it in the HTML output.

### Java Example

For a Java project containing `Calculator.java`:

```java
/** Utility math routines */
public class Calculator {
    // Adds two integers
    public static int add(int a, int b) {
        return a + b;
    }
}
```

Run the tool:

```bash
python docgenerator.py ./java_project --output ./docs
```

The generated docs list the `Calculator` class along with its public methods.

## GUI Usage

Install `PyQt5` to enable the graphical interface:

```bash
pip install pyqt5
```

Launch the GUI:

```bash
python gui_wrapper.py
```

The interface provides:

- Project and output directory selectors
- DocGen options such as including private functions and choosing languages (Python, MATLAB, C++, Java)
- A **Resume DocGen** button to continue generating documentation from cached progress
- ExplainCode options for selecting the output format and adding an optional data file

DocGen-LM auto-detects supported languages, so selecting them in the GUI is optional and provided for clarity.

To verify the new language options, launch the GUI and confirm that checkboxes for Python, MATLAB, C++, and Java are present under DocGen options.

## Using LMStudio as the Backend

1. Launch **LMStudio** and enable its API server (usually at `http://localhost:1234`).
2. Choose the local model you want LMStudio to serve.
3. Run the documentation generator and point it at the LMStudio API:

```bash
python docgenerator.py ./my_project --output ./docs --llm-url http://localhost:1234 --model local
```


## Running Tests

Install the test dependencies (including `pytest`) listed in `requirements.txt` and run:

```bash
pytest
```

## Sanitizing Existing Documentation

If assistant-style phrases slip into generated HTML files, clean them with:

```bash
python sanitize_docs.py ./docs
```

The command rewrites every `.html` file in the directory using the same filtering
applied during generation.

## Retrofitting Documentation Sidebars

Refresh sidebar navigation in existing HTML docs:

```bash
python retrofit_sidebar.py --source . --docs Docs
```

The script scans the source tree at `.` to build a hierarchical list of modules,
then replaces each `<div class="sidebar">` in `Docs/*.html` with a nested menu
reflecting that structure. Existing files are updated in place, giving the
current documentation a consistent module sidebar.

## Project Summary Utility

Generate a lightweight overview of an existing project and its documentation:

```bash
python explaincode.py --path ./my_project
```

Specify a custom destination for the summary with `--output`:

```bash
python explaincode.py --path ./my_project --output ./summaries
```

Set the manual title with `--title`:

```bash
python explaincode.py --path ./my_project --title "My Project Manual"
```

Use `--output-format pdf` to produce a PDF report (requires `reportlab`).

Control how text is split with `--chunking`:

| Mode    | Description                                                             |
|---------|-------------------------------------------------------------------------|
| `auto`  | Default. Chunk only when content exceeds token or character limits.     |
| `manual`| Always chunk content regardless of size.                                |
| `none`  | Disable chunking and warn if limits are exceeded.                       |

Auto mode uses built-in limits of **2,000 tokens** or **6,000 characters**. When
either threshold is exceeded, the text is split, each chunk is summarized, and
the partial summaries are merged into a single paragraph. If the merged text
still exceeds the limits, it is split and summarized again until the result
fits within bounds. Splitting favors
natural boundaries such as blank lines, Markdown headings, and fenced code
blocks so that paragraphs and examples remain intact.

Example usage:

```bash
python explaincode.py --chunking auto --path ./my_project
python explaincode.py --chunking manual --path ./my_project
python explaincode.py --chunking none --path ./my_project
```

When chunking is enabled, debug logs report the token and character count of
each chunk and the length of every response. Warnings are printed if chunking,
summarization, or the final merge step fails. Hierarchical merges are logged as
additional passes. If all chunks fail, the tool falls
back to `infer_sections`; if merging fails, partial summaries are concatenated.

The utility scans the entire project tree for documentation and sample files.
The generated manual is saved to the directory given by `--output` (defaulting
to the project path). Use `--insert-into-index` to append a link to the manual
into an existing `index.html` within that directory.

### Docs-first with Code Fallback

`explaincode.py` looks for documentation and sample files first. Each required
section gets a placeholder (e.g. `[[NEEDS_OVERVIEW]]`) if no text is found.
When placeholders remain, a second pass can analyse the project’s source code
to fill them in.

Code scanning is disabled by default. Enable it only when necessary with
`--scan-code-if-needed`, force it on with `--force-code`, or skip it entirely
with `--no-code`. Unresolved placeholders are stripped from the final manual.

Scanning code respects several limits (defaults shown):

| Flag                         | Default | Description                             |
|------------------------------|---------|-----------------------------------------|
| `--max-code-files`           | 12      | Maximum number of code files to scan    |
| `--code-time-budget-seconds` | 20      | Total seconds allowed for code scanning |
| `--max-bytes-per-file`       | 200000  | Maximum bytes read from each file       |

Example usage:

```bash
python explaincode.py --path ./my_project --no-code
python explaincode.py --path ./my_project --force-code
python explaincode.py --path ./my_project --scan-code-if-needed --max-code-files 20 --code-time-budget-seconds 60 --max-bytes-per-file 100000
```

Scanning more files or raising limits may slow the run. Logging reports which
sections are missing, when code scanning is triggered, and whether placeholders
were resolved.

## Error Handling

Both `docgenerator.py` and `explaincode.py` attempt to chunk large inputs and
merge the resulting summaries. If either step fails, a warning is printed and
the tools fall back to concatenating whatever partial responses were gathered.
When no partial responses are available, `explaincode.py` produces a minimal
summary using `infer_sections`. These errors do not affect exit codes, allowing
automation scripts to continue running.
