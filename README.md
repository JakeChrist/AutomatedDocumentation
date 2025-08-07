# DocGen-LM

DocGen-LM generates static HTML documentation for Python and MATLAB projects by analyzing source files and summarizing them with a local LLM. It now captures and renders **nested functions** and **subclasses**, so complex structures appear in the output as expandable sections.

## Prerequisites

- Python 3.9+
- LMStudio (or another compatible local LLM server)

## Installation

Clone the repository and install the required packages:

```bash
pip install -r requirements.txt
```

The tool depends on `requests`, `pygments`, and `beautifulsoup4`. It uses the
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

The LLM must be running and reachable via `llm_client.py`.

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
- DocGen options such as including private functions and choosing a language
- ExplainCode options for selecting the output format and adding an optional data file

## Using LMStudio as the Backend

1. Launch **LMStudio** and enable its API server (usually at `http://localhost:1234`).
2. Choose the local model you want LMStudio to serve.
3. Run the documentation generator and point it at the LMStudio API:

```bash
python docgenerator.py ./my_project --output ./docs --llm-url http://localhost:1234 --model local
```


## Running Tests

Install the test requirements (already included in requirements.txt) and run:

```bash
pytest
```

## Project Summary Utility

Generate a lightweight overview of an existing project and its documentation:

```bash
python explaincode.py --path ./my_project
```

Specify a custom destination for the summary with `--output`:

```bash
python explaincode.py --path ./my_project --output ./summaries
```

Use `--output-format pdf` to produce a PDF report (requires `reportlab`).

Control how text is split with `--chunking`:

| Mode    | Description                                                             |
|---------|-------------------------------------------------------------------------|
| `auto`  | Default. Chunk only when content exceeds token or character limits.     |
| `manual`| Always chunk content regardless of size.                                |
| `none`  | Disable chunking and warn if limits are exceeded.                       |

The utility scans the entire project tree for documentation and sample files.
The generated manual is saved to the directory given by `--output` (defaulting
to the project path). Use `--insert-into-index` to append a link to the manual
into an existing `index.html` within that directory.
