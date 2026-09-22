from entitygraph_rag.ingestion.filing_sections import detect_item_boundaries


def test_detect_item_boundaries_skips_toc():
    lines = [
        "Item 1.",  # TOC entry
        "Business",
        "4",
        "Item 1A.",  # TOC entry
        "Risk Factors",
        "12",
        "Item 1. Business",  # real header
        "This is a long paragraph about our business operations and products.",
        "Item 1A. Risk Factors",  # real header
        "This is a long paragraph describing numerous risk factors we face.",
    ]

    sections = detect_item_boundaries(lines)

    assert len(sections) == 2
    assert sections[0].item_key == "1"
    assert sections[1].item_key == "1A"
    assert any("business operations" in line for line in sections[0].lines)
    assert any("risk factors we face" in line for line in sections[1].lines)
    # TOC placeholder lines must not leak into either section's body.
    assert "4" not in sections[0].lines
    assert "12" not in sections[1].lines


def test_detect_item_boundaries_8k_dotted_and_next_line_title():
    lines = [
        "Item 8.01.",
        "",
        "Other Events.",
        "The company entered into a material definitive agreement.",
        "Item 9.01. Financial Statements and Exhibits.",
        "See attached exhibits for further details on the transaction.",
    ]

    sections = detect_item_boundaries(lines)

    assert [s.item_key for s in sections] == ["8.01", "9.01"]
    assert any("material definitive agreement" in line for line in sections[0].lines)
    assert any("attached exhibits" in line for line in sections[1].lines)


def test_detect_item_boundaries_dedupes_across_curly_and_straight_apostrophes():
    # Real EDGAR bug: the TOC uses a curly apostrophe ("Registrant’s")
    # while the real body header uses a straight one ("Registrant's") -
    # both must resolve to the same section, keeping only the real one.
    lines = [
        "Item 5.",
        "Market for Registrant’s Common Equity, Related Stockholder Matters",
        "4",
        "Item 5. Market for Registrant's Common Equity, Related Stockholder Matters",
        "This is the real body paragraph about equity and stockholder matters.",
        "Item 6. [Reserved]",
    ]

    sections = detect_item_boundaries(lines)

    assert len(sections) == 2
    assert sections[0].item_key == "5"
    assert any("real body paragraph" in line for line in sections[0].lines)


def test_no_boundaries_fallback():
    lines = ["Just some prose.", "No Item headings anywhere in this document."]

    sections = detect_item_boundaries(lines)

    assert len(sections) == 1
    assert sections[0].label == "FULL_DOCUMENT"
    assert sections[0].item_key is None
    assert sections[0].lines == lines
