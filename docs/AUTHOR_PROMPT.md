# GenRxiv Author Prompt

Paste this prompt into any LLM along with your research content. It
produces a Markdown document ready to submit to GenRxiv.

---

## The prompt

```
Write a research preprint as a single Markdown document.

Formatting requirements:

- Begin with a level-1 heading (#) containing the paper's title.
- Follow with an abstract: a short paragraph summarizing the work.
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
- Include a references section at the end. Use any consistent
  citation style.
- Include a section titled "AI Involvement" describing what parts of
  the work were AI-generated or co-generated, and with what tools.
  Be specific and honest — this is the point of GenRxiv.
- End with a license statement, such as:
  "This work is licensed under CC BY 4.0."

The document will be rendered to HTML with KaTeX for mathematics and
read on the web. Write for that medium: clear prose, well-structured
sections, and equations that read naturally in context.

Do not include YAML front matter, HTML, or LaTeX document commands
(\documentclass, \begin{document}, etc.). Plain Markdown only.
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
