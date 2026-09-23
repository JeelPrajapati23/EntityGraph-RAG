from reachfix.ingestion.transcript_sections import build_turn_sections


def test_short_transcript_turn_not_skipped():
    structured_content = [{"speaker": "Operator", "text": "Colette, why don't you start?"}]

    sections = build_turn_sections(structured_content)

    assert len(sections) == 1
    assert sections[0].label == "Operator"
    assert sections[0].lines == ["Colette, why don't you start?"]
    assert len(sections[0].lines[0].split()) == 5
