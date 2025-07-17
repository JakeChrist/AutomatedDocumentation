# DocGen-LM

DocGen-LM generates static HTML documentation for Python and MATLAB projects by analyzing source files and summarizing them with a local LLM.

## Prerequisites

- Python 3.9+
- LMStudio (or another compatible local LLM server)

## Installation

Clone the repository and install the required packages:

```bash
pip install -r requirements.txt
```

The tool depends on `requests`, `jinja2` and `pygments`.

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

For the complete specification see [Docs/DocGen-LM_SRS.md](Docs/DocGen-LM_SRS.md).
