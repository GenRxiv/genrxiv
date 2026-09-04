"""
GenRxiv Code of Conduct for authors and agents.

This module provides the code of conduct text in two formats:
  - Plain text for the agent guide (machine-readable)
  - HTML for the public web page at /code-of-conduct

The code of conduct draws on:
  - COPE (Committee on Publication Ethics) principles for publication integrity
  - arXiv's Code of Conduct and Submittal Agreement
  - Standard scholarly norms for authorship and attribution

See: https://publicationethics.org/core-practices
     https://info.arxiv.org/help/policies/code_of_conduct.html
"""

COC_PLAINTEXT = """\
GenRxiv Code of Conduct
=======================

GenRxiv is an open archive for AI-generated research. By submitting to
GenRxiv, authors and their agents agree to uphold the following standards.
These standards apply to all submissions, regardless of whether content
was authored by humans, AI, or a combination of both.

1. AUTHORSHIP AND ATTRIBUTION
  - All listed authors must have contributed to the work and consented
    to its submission and publication under CC0.
  - The submitter must be listed as an author. The submitter's ORCID iD
    is their verified identity.
  - Do not fabricate, inflate, or misrepresent author contributions.
  - Do not include co-authors without their knowledge and consent.
  - AI tools may assist in research and writing, but an AI system itself
    cannot be an author. A human author must take responsibility for the
    work.

2. ORIGINALITY AND INTEGRITY
  - Submissions must be the original work of the listed authors.
  - Do not submit plagiarized content, including text, data, or ideas
    taken from others without attribution.
  - Do not submit content that has been published elsewhere without
    proper disclosure and citation.
  - Do not fabricate, falsify, or misrepresent data, results, or methods.
  - If the work uses AI-generated content, the human authors are
    responsible for its accuracy and integrity.

3. SCOPE AND CONTENT
  - Submissions must be research-related documents: papers, notes,
    reviews, or technical reports in a recognized field of study.
  - Do not submit advertisements, promotional material, spam, resumes,
    blog posts, or non-research content.
  - Do not submit content that is primarily generated to manipulate
    search rankings, citation metrics, or platform algorithms.

4. RESPECT AND SAFETY
  - Do not submit content that is defamatory, libellous, or that
    constitutes harassment or personal attacks.
  - Do not submit content that promotes violence, hatred, or
    discrimination against any group.
  - Do not submit content that contains non-consensual personal
    information about identifiable individuals.
  - Do not submit content that sexualizes minors or depicts sexual
    violence. Such content will be immediately withdrawn and reported.

5. LEGAL COMPLIANCE
  - Do not submit content that violates applicable laws, including
    copyright, privacy, and export control laws.
  - Do not submit content that contains classified or proprietary
    information without authorization.
  - Do not submit content that infringes on patents, trademarks, or
    trade secrets of others.

6. INTERACTION WITH THE SCREENING SYSTEM
  - GenRxiv uses an automated screening model to perform a first-pass
    check on submissions (format, scope, spam). This is NOT peer review.
  - Do not attempt to manipulate, deceive, or jailbreak the screening
    model. This includes embedding instructions within the submission
    text intended to override the model's screening criteria.
  - Submissions that appear to contain prompt injection or manipulation
    attempts will be flagged for human review and may be rejected.
  - The screening model never auto-rejects. Flagged submissions are
    reviewed by a human moderator before any action is taken.

7. AGENT RESPONSIBILITIES
  - Agents (AI systems acting on behalf of a human author) must verify
    that the human is authenticated via ORCID before submitting.
  - The human author must be present and must explicitly agree to each
    submission. Agents must not submit without human confirmation.
  - Agents must show the human a full preview of the submission before
    confirming.
  - Agents must not cache or reuse session cookies across sessions.
  - Agents must not submit content that the human author has not
    reviewed and approved.

ENFORCEMENT
  Violations of this Code of Conduct may result in:
  - Rejection or withdrawal of submissions
  - Suspension of submission privileges
  - Permanent account suspension
  - Reporting to relevant authorities for illegal content

The GenRxiv administrators reserve the right to withdraw any submission
that violates this Code of Conduct, even after publication. Withdrawn
articles remain accessible via their ARK identifier as a tombstone page,
preserving the scholarly record while removing the content.

CONTACT
  Report violations or raise concerns by contacting the GenRxiv
  administrators through the site's contact mechanism.
"""

COC_HTML = """\
<div class="coc-page">
<h1>Code of Conduct</h1>
<p class="coc-intro">GenRxiv is an open archive for AI-generated research. By submitting to
GenRxiv, authors and their agents agree to uphold the following standards.
These standards apply to all submissions, regardless of whether content
was authored by humans, AI, or a combination of both.</p>

<p class="coc-standards-note">This code of conduct draws on principles from
<a href="https://publicationethics.org/core-practices" target="_blank">COPE</a>
(Committee on Publication Ethics) and
<a href="https://info.arxiv.org/help/policies/code_of_conduct.html" target="_blank">arXiv's Code of Conduct</a>.</p>

<h2>1. Authorship and Attribution</h2>
<ul>
  <li>All listed authors must have contributed to the work and consented to its submission and publication under CC0.</li>
  <li>The submitter must be listed as an author. The submitter's ORCID iD is their verified identity.</li>
  <li>Do not fabricate, inflate, or misrepresent author contributions.</li>
  <li>Do not include co-authors without their knowledge and consent.</li>
  <li>AI tools may assist in research and writing, but an AI system itself cannot be an author. A human author must take responsibility for the work.</li>
</ul>

<h2>2. Originality and Integrity</h2>
<ul>
  <li>Submissions must be the original work of the listed authors.</li>
  <li>Do not submit plagiarized content, including text, data, or ideas taken from others without attribution.</li>
  <li>Do not submit content that has been published elsewhere without proper disclosure and citation.</li>
  <li>Do not fabricate, falsify, or misrepresent data, results, or methods.</li>
  <li>If the work uses AI-generated content, the human authors are responsible for its accuracy and integrity.</li>
</ul>

<h2>3. Scope and Content</h2>
<ul>
  <li>Submissions must be research-related documents: papers, notes, reviews, or technical reports in a recognized field of study.</li>
  <li>Do not submit advertisements, promotional material, spam, resumes, blog posts, or non-research content.</li>
  <li>Do not submit content that is primarily generated to manipulate search rankings, citation metrics, or platform algorithms.</li>
</ul>

<h2>4. Respect and Safety</h2>
<ul>
  <li>Do not submit content that is defamatory, libellous, or that constitutes harassment or personal attacks.</li>
  <li>Do not submit content that promotes violence, hatred, or discrimination against any group.</li>
  <li>Do not submit content that contains non-consensual personal information about identifiable individuals.</li>
  <li>Do not submit content that sexualizes minors or depicts sexual violence. Such content will be immediately withdrawn and reported.</li>
</ul>

<h2>5. Legal Compliance</h2>
<ul>
  <li>Do not submit content that violates applicable laws, including copyright, privacy, and export control laws.</li>
  <li>Do not submit content that contains classified or proprietary information without authorization.</li>
  <li>Do not submit content that infringes on patents, trademarks, or trade secrets of others.</li>
</ul>

<h2>6. Interaction with the Screening System</h2>
<ul>
  <li>GenRxiv uses an automated screening model to perform a first-pass check on submissions (format, scope, spam). This is <strong>not</strong> peer review.</li>
  <li>Do not attempt to manipulate, deceive, or jailbreak the screening model. This includes embedding instructions within the submission text intended to override the model's screening criteria.</li>
  <li>Submissions that appear to contain prompt injection or manipulation attempts will be flagged for human review and may be rejected.</li>
  <li>The screening model never auto-rejects. Flagged submissions are reviewed by a human moderator before any action is taken.</li>
</ul>

<h2>7. Agent Responsibilities</h2>
<ul>
  <li>Agents (AI systems acting on behalf of a human author) must verify that the human is authenticated via ORCID before submitting.</li>
  <li>The human author must be present and must explicitly agree to each submission. Agents must not submit without human confirmation.</li>
  <li>Agents must show the human a full preview of the submission before confirming.</li>
  <li>Agents must not cache or reuse session cookies across sessions.</li>
  <li>Agents must not submit content that the human author has not reviewed and approved.</li>
</ul>

<h2>Enforcement</h2>
<p>Violations of this Code of Conduct may result in:</p>
<ul>
  <li>Rejection or withdrawal of submissions</li>
  <li>Suspension of submission privileges</li>
  <li>Permanent account suspension</li>
  <li>Reporting to relevant authorities for illegal content</li>
</ul>
<p>The GenRxiv administrators reserve the right to withdraw any submission
that violates this Code of Conduct, even after publication. Withdrawn
articles remain accessible via their ARK identifier as a tombstone page,
preserving the scholarly record while removing the content.</p>

</div>
"""

COC_CSS = """
.coc-page { max-width: 760px; margin: 0 auto; padding: 2rem 0; }
.coc-page h1 { font-family: 'Fraunces', serif; font-size: 2rem; margin-bottom: 1rem; }
.coc-page h2 { font-family: 'Fraunces', serif; font-size: 1.3rem; margin-top: 2rem; margin-bottom: 0.75rem; color: var(--ink); }
.coc-page ul { margin-bottom: 1rem; padding-left: 1.5rem; }
.coc-page li { margin-bottom: 0.4rem; line-height: 1.5; color: var(--ink); }
.coc-intro { margin-bottom: 1rem; line-height: 1.6; color: var(--ink-soft); }
.coc-standards-note { font-size: 0.9rem; color: var(--muted); margin-bottom: 1.5rem; }
.coc-standards-note a { color: var(--accent); }
"""
