// Co-author ORCID lookup
function normalizeOrcid(id) {
    id = id.trim().replace(/\s/g, '');
    if (id.length === 16 && !id.includes('-')) {
        return id.slice(0,4) + '-' + id.slice(4,8) + '-' + id.slice(8,12) + '-' + id.slice(12,16);
    }
    return id;
}

function lookupOrcid(input, nameSpan) {
    const raw = input.value.trim();
    if (!raw) { nameSpan.textContent = ''; nameSpan.className = 'author-name'; return; }
    const orcid = normalizeOrcid(raw);
    if (!/^\d{4}-\d{4}-\d{4}-\d{4}$/.test(orcid)) {
        nameSpan.textContent = 'Invalid ORCID format';
        nameSpan.className = 'author-name not-found';
        return;
    }
    nameSpan.textContent = 'Looking up...';
    nameSpan.className = 'author-name loading';
    fetch('/api/orcid-lookup/' + orcid)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (data) {
                nameSpan.textContent = data.name + (data.affiliation ? ' \u00b7 ' + data.affiliation : '');
                nameSpan.className = 'author-name';
                input.dataset.name = data.name;
            } else {
                nameSpan.textContent = 'Not found \u2014 check the ORCID iD';
                nameSpan.className = 'author-name not-found';
                delete input.dataset.name;
            }
        })
        .catch(() => {
            nameSpan.textContent = 'Lookup failed';
            nameSpan.className = 'author-name not-found';
            delete input.dataset.name;
        });
    updatePreviewState();
}

function addAuthorRow(orcid, name) {
    const container = document.getElementById('co-authors');
    const div = document.createElement('div');
    div.className = 'author-entry';
    const input = document.createElement('input');
    input.type = 'text';
    input.name = 'co_author_orcids';
    input.placeholder = '0000-0000-0000-0000';
    input.value = orcid || '';
    input.style.padding = '0.6rem';
    input.style.border = '1px solid var(--border)';
    input.style.borderRadius = '4px';
    input.style.fontSize = '0.95rem';
    input.style.flex = '1';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'author-name';
    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'move-author-up';
    upBtn.innerHTML = '&#8593;';
    upBtn.title = 'Move up';
    upBtn.onclick = function() { moveAuthorUp(this); };
    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'move-author-down';
    downBtn.innerHTML = '&#8595;';
    downBtn.title = 'Move down';
    downBtn.onclick = function() { moveAuthorDown(this); };
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'remove-author';
    removeBtn.textContent = 'Remove';
    removeBtn.onclick = function() { div.remove(); updatePreviewState(); };
    input.addEventListener('input', function() {
        clearTimeout(input.timer);
        input.timer = setTimeout(function() { lookupOrcid(input, nameSpan); }, 400);
    });
    div.appendChild(input);
    div.appendChild(nameSpan);
    div.appendChild(upBtn);
    div.appendChild(downBtn);
    div.appendChild(removeBtn);
    container.appendChild(div);
    if (orcid) lookupOrcid(input, nameSpan);
    updatePreviewState();
}

function moveAuthorUp(btn) {
    var entry = btn.parentElement;
    var prev = entry.previousElementSibling;
    if (prev && prev.classList.contains('author-entry')) {
        entry.parentNode.insertBefore(entry, prev);
        updatePreviewState();
    }
}

function moveAuthorDown(btn) {
    var entry = btn.parentElement;
    var next = entry.nextElementSibling;
    if (next && next.classList.contains('author-entry')) {
        entry.parentNode.insertBefore(next, entry);
        updatePreviewState();
    }
}

// ─── Classification rows: domain → subdomain ─────────────────────────────
function buildClassRow(num) {
    var row = document.createElement('div');
    row.className = 'class-row';

    var label = document.createElement('span');
    label.className = 'class-num';
    label.textContent = num + '.';

    var domainSel = document.createElement('select');
    domainSel.className = 'class-domain';
    domainSel.dataset.row = num;
    domainSel.innerHTML = '<option value="">Select domain...</option>' +
        Object.keys(OECD_DATA).map(function(k) { return '<option value="' + k + '">' + k + '</option>'; }).join('');

    var subSel = document.createElement('select');
    subSel.className = 'class-subdomain';
    subSel.dataset.row = num;
    subSel.disabled = true;
    subSel.innerHTML = '<option value="">Select subdomain...</option>';

    domainSel.addEventListener('change', function() {
        var domain = domainSel.value;
        subSel.innerHTML = '<option value="">Select subdomain...</option>';
        if (domain) {
            var subs = OECD_DATA[domain];
            subSel.innerHTML += subs.map(function(s) { return '<option value="' + domain + ' > ' + s + '">' + s + '</option>'; }).join('');
            subSel.disabled = false;
        } else {
            subSel.disabled = true;
        }
        updateClassRowState(row);
        updatePreviewState();
    });

    subSel.addEventListener('change', function() {
        updateClassRowState(row);
        updatePreviewState();
    });

    row.appendChild(label);
    row.appendChild(domainSel);
    row.appendChild(subSel);
    return row;
}

function updateClassRowState(row) {
    var domainSel = row.querySelector('.class-domain');
    var subSel = row.querySelector('.class-subdomain');
    if (domainSel.value && subSel.value) {
        domainSel.classList.add('complete');
        subSel.classList.add('complete');
    } else {
        domainSel.classList.remove('complete');
        subSel.classList.remove('complete');
    }
}

function getSelectedClassifications() {
    var rows = document.querySelectorAll('.class-row');
    var selections = [];
    rows.forEach(function(row) {
        var sub = row.querySelector('.class-subdomain');
        if (sub && sub.value) selections.push(sub.value);
    });
    return selections;
}

function getClassificationCount() {
    return getSelectedClassifications().length;
}

// ─── Preview button state management ──────────────────────────────────────
function getMissingItems() {
    var missing = [];
    var title = document.querySelector('[name="title"]').value.trim();
    var abstract = document.querySelector('[name="abstract"]').value.trim();
    var mdFile = document.querySelector('[name="markdown"]').files[0];
    var classCount = getClassificationCount();
    var reviewed = document.querySelector('[name="reviewed"]').checked;
    var cc0 = document.querySelector('[name="cc0_agree"]').checked;
    var coc = document.querySelector('[name="coc_agree"]').checked;

    if (!title) missing.push('title');
    if (!abstract) missing.push('abstract');
    if (!mdFile) missing.push('Markdown file');
    if (classCount < 3) missing.push((3 - classCount) + ' more classification' + ((3 - classCount) > 1 ? 's' : ''));
    if (!reviewed) missing.push('review confirmation');
    if (!cc0) missing.push('CC0 agreement');
    if (!coc) missing.push('Code of Conduct agreement');
    return missing;
}

function updatePreviewState() {
    var btn = document.getElementById('preview-btn');
    var hints = document.getElementById('preview-hints');
    var missing = getMissingItems();

    if (missing.length === 0) {
        btn.className = 'btn-preview ready';
        btn.disabled = false;
        hints.innerHTML = '<span class="all-ready">All requirements met \u2014 ready to preview.</span>';
    } else {
        btn.className = 'btn-preview disabled';
        btn.disabled = true;
        hints.innerHTML = '<span class="missing-item">Still needed: ' + missing.join(', ') + '</span>';
    }
}

// ─── Preview step ─────────────────────────────────────────────────────────
function showPreview(e) {
    e.preventDefault();
    if (getMissingItems().length > 0) return;

    var title = document.querySelector('[name="title"]').value.trim();
    var abstract = document.querySelector('[name="abstract"]').value.trim();
    var mdFile = document.querySelector('[name="markdown"]').files[0];
    var subjects = getSelectedClassifications();

    // Gather all authors from the author entries
    // The submitter is included as an author entry (first, with a "you" label)
    // but author order is determined by the entries, not forced.
    var authors = [];
    var allAuthorInputs = document.querySelectorAll('.author-entry input[type="text"]');
    allAuthorInputs.forEach(function(input) {
        var orcid = normalizeOrcid(input.value);
        if (orcid && /^\d{4}-\d{4}-\d{4}-\d{4}$/.test(orcid)) {
            var name = input.dataset.name || input.parentElement.querySelector('.author-name').textContent.split(' \u00b7 ')[0] || 'Unknown';
            if (name && !name.includes('Not found') && !name.includes('Looking') && !name.includes('Invalid') && !name.includes('failed')) {
                authors.push({orcid: orcid, name: name});
            }
        }
    });

    // Build preview
    var authorsHtml = authors.map(function(a) {
        return '<div class="author-line">' + a.name + ' <span class="orcid">' + a.orcid + '</span></div>';
    }).join('');
    var subjHtml = subjects.map(function(k) { return '<span class="subject-tag">' + k + '</span>'; }).join(' ');

    document.getElementById('preview-title').textContent = title;
    document.getElementById('preview-abstract').textContent = abstract;
    document.getElementById('preview-authors').innerHTML = authorsHtml;
    document.getElementById('preview-subjects').innerHTML = subjHtml;
    document.getElementById('preview-file').textContent = mdFile.name + ' (' + (mdFile.size / 1024).toFixed(1) + ' KB)';

    // Store authors JSON for final submission
    document.getElementById('authors-json').value = JSON.stringify(authors);

    // Copy values to confirm form
    document.getElementById('confirm-title').value = title;
    document.getElementById('confirm-abstract').value = abstract;
    document.getElementById('confirm-authors').value = JSON.stringify(authors);
    document.getElementById('confirm-subjects').value = subjects.join(', ');
    // Copy agreement checkbox states
    document.getElementById('confirm-reviewed').value = document.querySelector('[name="reviewed"]').checked ? '1' : '';
    document.getElementById('confirm-cc0').value = document.querySelector('[name="cc0_agree"]').checked ? '1' : '';
    document.getElementById('confirm-coc').value = document.querySelector('[name="coc_agree"]').checked ? '1' : '';
    // Copy the file to the confirm form's file input
    // DataTransfer is needed because .files is read-only
    var confirmFile = document.getElementById('confirm-markdown');
    try {
        var dt = new DataTransfer();
        dt.items.add(mdFile);
        confirmFile.files = dt.files;
    } catch (err) {
        console.error('Could not copy file to confirm form:', err);
    }

    // Show preview, hide form
    document.getElementById('submit-form').style.display = 'none';
    document.getElementById('preview-section').style.display = 'block';
}

function backToForm(e) {
    e.preventDefault();
    document.getElementById('submit-form').style.display = 'block';
    document.getElementById('preview-section').style.display = 'none';
}

// ─── YAML front matter auto-fill ──────────────────────────────────────────
// When a Markdown file is selected, send it to /api/validate which
// parses front matter using PyYAML (the same parser the API uses).
// The response includes parsed_metadata with title, abstract, authors,
// and subjects extracted from the file's YAML front matter.

function fillFormFromFrontMatter(meta) {
    if (!meta) return;

    // Title
    if (meta.title) {
        var titleInput = document.querySelector('[name="title"]');
        if (titleInput) titleInput.value = meta.title;
    }

    // Abstract
    if (meta.abstract) {
        var abstractInput = document.querySelector('[name="abstract"]');
        if (abstractInput) abstractInput.value = meta.abstract;
    }

    // Authors (array of {orcid, name} objects) — replaces all author entries
    // The submitter must always be present; if the front matter doesn't
    // include them, they are appended.
    if (meta.authors && Array.isArray(meta.authors)) {
        var container = document.getElementById('co-authors');
        var submitterOrcid = document.querySelector('[data-submitter="true"] input');
        var myOrcid = submitterOrcid ? normalizeOrcid(submitterOrcid.value) : null;
        var myName = submitterOrcid ? submitterOrcid.dataset.name : null;
        // Remove all existing author entries
        container.innerHTML = '';

        var foundSubmitter = false;
        meta.authors.forEach(function(a) {
            if (a.orcid && a.name) {
                addAuthorRow(a.orcid, a.name);
                if (myOrcid && normalizeOrcid(a.orcid) === myOrcid) foundSubmitter = true;
            }
        });
        // If the submitter wasn't in the front matter, add them
        if (!foundSubmitter && myOrcid && myName) {
            addAuthorRow(myOrcid, myName);
        }
    }

    // Subjects (array of "Domain > Subdomain" strings)
    if (meta.subjects && Array.isArray(meta.subjects)) {
        var rows = document.querySelectorAll('.class-row');
        meta.subjects.forEach(function(subj, idx) {
            if (idx >= rows.length) return;
            var parts = subj.split(' > ');
            var domain = parts[0].trim();
            var subdomain = parts[1] ? parts[1].trim() : '';

            var domainSel = rows[idx].querySelector('.class-domain');
            var subSel = rows[idx].querySelector('.class-subdomain');

            // Set domain
            domainSel.value = domain;
            // Trigger change to populate subdomain options
            domainSel.dispatchEvent(new Event('change'));

            // Set subdomain if we have a value
            if (subdomain) {
                // The option value is "Domain > Subdomain"
                var fullValue = domain + ' > ' + subdomain;
                subSel.value = fullValue;
                subSel.dispatchEvent(new Event('change'));
            }
        });
    }

    // Update preview state after filling
    updatePreviewState();
}

function handleFileSelect(input) {
    if (!input.files || !input.files.length) return;
    var file = input.files[0];
    // Send the file to /api/validate to parse front matter using the
    // same PyYAML parser as the API — no hand-written JS YAML parser.
    var formData = new FormData();
    formData.append('markdown', file);
    fetch('/api/validate', {
        method: 'POST',
        body: formData,
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.parsed_metadata) {
            fillFormFromFrontMatter(data.parsed_metadata);
        }
    })
    .catch(function(err) {
        console.error('Front matter parse failed:', err);
    });
}

// ─── Init ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    // Build 3 classification rows
    var classContainer = document.getElementById('classification-rows');
    for (var i = 1; i <= 3; i++) {
        classContainer.appendChild(buildClassRow(i));
    }

    // Add co-author button
    document.getElementById('add-author-btn').addEventListener('click', function() {
        addAuthorRow('', '');
    });

    // File input: auto-fill from YAML front matter
    var fileInput = document.querySelector('[name="markdown"]');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            handleFileSelect(this);
        });
    }

    // Monitor all inputs for preview state updates
    var form = document.getElementById('main-form');
    if (form) {
        form.addEventListener('input', updatePreviewState);
        form.addEventListener('change', updatePreviewState);
    }

    // Initial state
    updatePreviewState();
});

// beforeunload: check form state directly — no dependency on event listeners
var _submitConfirmed = false;
function _formHasData() {
    var form = document.getElementById('main-form');
    if (!form) return false;
    var hasData = false;
    form.querySelectorAll('input[type="text"], textarea').forEach(function(el) {
        if (el.value.trim()) hasData = true;
    });
    var fileInput = form.querySelector('input[type="file"]');
    if (fileInput && fileInput.files && fileInput.files.length > 0) hasData = true;
    form.querySelectorAll('input[type="checkbox"]').forEach(function(el) {
        if (el.checked) hasData = true;
    });
    form.querySelectorAll('select').forEach(function(el) {
        if (el.value) hasData = true;
    });
    form.querySelectorAll('input[name="co_author_orcids"]').forEach(function(el) {
        if (el.value.trim()) hasData = true;
    });
    return hasData;
}

window.addEventListener('beforeunload', function(e) {
    if (_submitConfirmed) return;
    if (_formHasData()) {
        e.preventDefault();
        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
        return 'You have unsaved changes. Are you sure you want to leave?';
    }
});

// Also intercept nav link clicks and form submits for an explicit confirm()
// This is a fallback in case beforeunload doesn't fire
document.addEventListener('DOMContentLoaded', function() {
    var nav = document.querySelector('nav');
    if (!nav) return;
    // Intercept all links in the nav
    nav.querySelectorAll('a[href]').forEach(function(link) {
        link.addEventListener('click', function(e) {
            if (_submitConfirmed) return;
            if (!_formHasData()) return;
            if (!confirm('You have unsaved changes. Are you sure you want to leave?')) {
                e.preventDefault();
            }
        });
    });
    // Intercept form submissions in the nav (e.g. Sign out)
    nav.querySelectorAll('form').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (_submitConfirmed) return;
            if (!_formHasData()) return;
            if (!confirm('You have unsaved changes. Are you sure you want to leave?')) {
                e.preventDefault();
            }
        });
    });
});

// Intercept confirm form submit — post via fetch, redirect to submission page
document.addEventListener('DOMContentLoaded', function() {
    var confirmForm = document.getElementById('confirm-form');
    if (confirmForm) {
        confirmForm.addEventListener('submit', function(e) {
            e.preventDefault();
            _submitConfirmed = true;
            var btn = confirmForm.querySelector('button[type="submit"]');
            btn.disabled = true;
            btn.textContent = 'Submitting...';
            fetch('/api/submit', {
                method: 'POST',
                body: new FormData(confirmForm),
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.id) {
                    window.location.href = '/submit/done/' + data.id;
                } else {
                    alert('Submission failed: ' + (data.detail || JSON.stringify(data)));
                    btn.disabled = false;
                    btn.textContent = 'Confirm and submit';
                }
            })
            .catch(function(err) {
                alert('Submission failed: ' + err);
                btn.disabled = false;
                btn.textContent = 'Confirm and submit';
            });
        });
    }
});
