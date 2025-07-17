# DocGen-LM

A small tool that generates HTML documentation for Python and MATLAB projects using a local LLM backend. It scans a source tree, summarizes code with the LLM and writes a set of static pages.

## Usage

Run the generator by pointing it at the project directory and an output location:

```bash
python docgenerator.py ./my_project --output ./docs
```

Files or directories may be skipped with ``--ignore`` which can be repeated:

```bash
python docgenerator.py ./my_project --output ./docs --ignore tests --ignore build
```

Ensure that LMStudio or another compatible LLM server is running and reachable before invoking the script.
