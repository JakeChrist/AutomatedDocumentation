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

## 7. 🧪 CLI Usage

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

## Documentation

Generated HTML documentation can be found in the **Docs/** directory.
