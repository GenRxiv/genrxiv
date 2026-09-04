# GenRxiv Author Prompt

Paste this prompt into any LLM along with your research content. It
produces a Markdown document ready to submit to GenRxiv.

---

## The prompt

```
Write a research preprint as a single Markdown document.

Formatting requirements:

- Begin with YAML front matter containing all submission metadata:

  ---
  title: "Paper Title"
  abstract: "A brief summary of the research."
  authors:
    - orcid: "0000-0000-0000-0000"
      name: "Author Name"
    - orcid: "0000-0000-0000-0001"
      name: "Co-Author Name"
  subjects:
    - "Natural sciences > Mathematics"
    - "Natural sciences > Computer and information sciences"
    - "Social sciences > Economics and business"
  ---

  The front matter fills out the submission form automatically when
  the file is uploaded. The authors list is the complete author list
  in publication order — the first entry is the lead author. Include
  all authors, including the submitter if they are an author.
  Exactly 3 subjects are required, using "Domain > Subdomain" format
  from the OECD FOS taxonomy (see https://genrxiv.org/api/fos).
- After the front matter, begin the body with a level-1 heading (#)
  containing the paper's title.
- Follow with the abstract as a paragraph (or it can be in the front
  matter only — the front matter version is what gets indexed).
- Organize the body into sections using level-2 headings (##).
  Choose whatever section structure suits the work — there is no
  required template.
- Write mathematics using LaTeX notation inside dollar signs:
  inline math as $x^2 + y^2$ and displayed equations on their own
  lines as $$ \int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2} $$
- Reference figures as Markdown images: ![Figure caption](figure.svg)
  Prefer SVG for figures and diagrams. If you cannot produce SVG,
  describe the figure in text and note where an image should be
  inserted.
- Cite references inline using Pandoc's @citekey syntax:
  "As shown by Smith et al. [@smith2023], the method converges."
  Multiple citations: [@smith2023; @jones2024].
- Include a references section at the end as a fenced BibTeX code block:

  ```bibtex
  @article{smith2023,
    author = {Smith, Jane and Doe, John},
    title = {A Method for Testing},
    journal = {Journal of Testing},
    year = {2023},
    volume = {1},
    pages = {1--10},
    doi = {10.1234/example}
  }

  @book{jones2024,
    author = {Jones, Bob},
    title = {Another Reference},
    publisher = {Academic Press},
    year = {2024}
  }
  ```

  The server extracts the BibTeX block, renders citations as
  numbered references [1], [2] in citation order, and hides the
  raw BibTeX from the rendered HTML. The BibTeX is also exposed
  via /article/{ark}/bibtex for machine-readable access.
- Include a section titled "AI Involvement" describing what parts of
  the work were AI-generated or co-generated, and with what tools.
  Be specific and honest — this is the point of GenRxiv.
- End with a license statement:
  "This work is licensed under CC0 1.0 (Public Domain Dedication)."

The document will be rendered to HTML with KaTeX for mathematics and
read on the web. Write for that medium: clear prose, well-structured
sections, and equations that read naturally in context.

Do not include HTML or LaTeX document commands (\documentclass,
\begin{document}, etc.). Plain Markdown only (YAML front matter is
allowed and recommended for metadata).
```

---

## Why this format

GenRxiv stores the Markdown source, not a rendered PDF. When the paper
is published, the server renders the Markdown to HTML with
[KaTeX](https://katex.org/) for math. This keeps every paper small
(kilobytes, not megabytes), readable by both people and machines, and
printable directly from the browser.

## Figure guidance

- **SVG** — preferred. Vector graphics are small, sharp at any zoom
  level, and render natively in the browser.
- **PNG/JPG** — accepted with limits: 500 KB per image, 2 MB total
  per submission.
- **No figure available?** — describe it in text. A clear textual
  description is more useful to readers and machines than a missing
  image.
