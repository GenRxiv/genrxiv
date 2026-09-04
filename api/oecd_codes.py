"""OECD Fields of Science classification codes and colors.

Maps the 6 OECD FOS domains to single-letter codes and colors, and
subdomains to short abbreviations. Used for compact colored tags in
the UI, e.g., [N·CS] for "Natural sciences > Computer and information
sciences".
"""

# Domain → (letter, color, background color)
DOMAIN_CODES = {
    "Natural sciences": ("N", "#2F5CFF", "#E4E9FF"),
    "Engineering and technology": ("E", "#E67E22", "#FDF0E0"),
    "Medical and health sciences": ("M", "#E74C3C", "#FDEAEA"),
    "Agricultural and veterinary sciences": ("A", "#27AE60", "#E8F8F0"),
    "Social sciences": ("S", "#9B59B6", "#F4ECF7"),
    "Humanities and the arts": ("H", "#16A085", "#E0F5F1"),
}

# Subdomain → abbreviation
SUBDOMAIN_CODES = {
    # Natural sciences
    "Mathematics": "MATH",
    "Computer and information sciences": "CS",
    "Physical sciences": "PHYS",
    "Chemical sciences": "CHEM",
    "Earth and related environmental sciences": "EARTH",
    "Biological sciences": "BIO",
    "Other natural sciences": "OTHER",
    # Engineering and technology
    "Civil engineering": "CIVIL",
    "Electrical, electronic, information engineering": "EE",
    "Mechanical engineering": "MECH",
    "Chemical engineering": "CHE",
    "Materials engineering": "MAT",
    "Medical engineering": "MEDENG",
    "Environmental engineering": "ENV",
    "Environmental biotechnology": "EBIOT",
    "Industrial biotechnology": "IBIO",
    "Nano-technology": "NANO",
    "Other engineering and technologies": "OTHER",
    # Medical and health sciences
    "Basic medicine": "BASIC",
    "Clinical medicine": "CLIN",
    "Health sciences": "HEALTH",
    "Medical biotechnology": "MEDBIO",
    "Other medical sciences": "OTHER",
    # Agricultural and veterinary sciences
    "Agriculture, forestry, and fisheries": "AGRI",
    "Animal and dairy science": "ANIM",
    "Veterinary science": "VET",
    "Agricultural biotechnology": "AGBIO",
    "Other agricultural sciences": "OTHER",
    # Social sciences
    "Psychology and cognitive sciences": "PSYCH",
    "Economics and business": "ECON",
    "Education": "EDU",
    "Sociology": "SOC",
    "Law": "LAW",
    "Political science": "POL",
    "Social and economic geography": "GEOG",
    "Media and communications": "MEDIA",
    "Other social sciences": "OTHER",
    # Humanities and the arts
    "History and archaeology": "HIST",
    "Languages and literature": "LANG",
    "Philosophy, ethics, and religion": "PHIL",
    "Arts (arts, history of arts, performing arts, music)": "ARTS",
    "Other humanities": "OTHER",
}


def get_domain_code(domain: str) -> tuple[str, str, str]:
    """Return (letter, color, bg_color) for a domain. Defaults to gray."""
    return DOMAIN_CODES.get(domain, ("?", "#888", "#f0f0f0"))


def get_subdomain_code(subdomain: str) -> str:
    """Return short abbreviation for a subdomain. Defaults to the full name."""
    return SUBDOMAIN_CODES.get(subdomain, subdomain[:4].upper())


def parse_classification(classification: str) -> tuple[str, str, str, str, str, str]:
    """Parse a 'Domain > Subdomain' string into display components.

    Returns (domain, subdomain, domain_letter, domain_color,
             domain_bg, subdomain_code).
    """
    parts = classification.split(" > ", 1)
    domain = parts[0].strip()
    subdomain = parts[1].strip() if len(parts) > 1 else ""
    letter, color, bg = get_domain_code(domain)
    sub_code = get_subdomain_code(subdomain)
    return domain, subdomain, letter, color, bg, sub_code


def classification_tag(classification: str) -> str:
    """Render a colored subject tag for a classification string.

    Uses data-tooltip (CSS-based) instead of the title attribute so
    tooltips work on touch devices (iPad, iPhone) via tap-to-focus.

    E.g., 'Natural sciences > Computer and information sciences' becomes:
    <span class="oecd-tag" tabindex="0" data-tooltip="..." style="...">N·CS</span>
    """
    domain, subdomain, letter, color, bg, sub_code = parse_classification(classification)
    label = f"{letter}·{sub_code}" if sub_code else letter
    return (
        f'<span class="oecd-tag" tabindex="0" '
        f'style="color:{color};background:{bg};border-color:{color}" '
        f'data-tooltip="{classification}">{label}</span>'
    )
