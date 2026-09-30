from trafficlegal.ingest import MUTCD_HEADING, parse_provision_text


def test_mutcd_section_4f17_paragraph_structure(assistant):
    section = assistant.rag.section("MUTCD11", "4F.17")
    assert section["title"] == "Yellow Change and Red Clearance Intervals"
    paras = {p["para_no"]: p for p in section["paragraphs"]}
    assert paras["08"]["provision"] == "Standard" and "shall not vary" in paras["08"]["text"]
    assert paras["13"]["provision"] == "Guidance" and "3 seconds" in paras["13"]["text"]


def test_parser_handles_inline_paragraph_numbers_from_pypdf():
    lines = ["Section 4F.17 Yellow Change and Red Clearance Intervals", "Standard:",
             "01  The duration shall be determined using engineering practices.", "Guidance:",
             "02  A yellow change interval should have a minimum duration of 3 seconds."]
    sections = parse_provision_text(lines, "T", MUTCD_HEADING)
    assert [(p.para_no, p.provision) for p in sections[0].paragraphs] == [("01", "Standard"), ("02", "Guidance")]


def test_cross_references_are_not_mistaken_for_headings():
    lines = ["Section 4F.16 Signal Indications for Approaches", "Support:", "01 Text.",
             "Section 4F.16 contains information regarding the signalization of approaches"]
    sections = parse_provision_text(lines, "T", MUTCD_HEADING)
    assert len(sections) == 1


def test_jurisdiction_routing_never_mixes_states(assistant):
    results = assistant.rag.retrieve("minimum yellow change interval", state_code="KS", jurisdiction_code="NGT", k=12)
    docs = {r.doc_id for r in results}
    assert "STATE_AV" not in docs and not any(d.startswith("LOCAL_") and d != "LOCAL_NGT" for d in docs)
    assert "LOCAL_NGT" in docs and "MUTCD11" in docs


def test_retrieval_finds_the_yellow_interval_section(assistant):
    top = assistant.rag.retrieve("can the yellow change interval vary from cycle to cycle", tiers=("FEDERAL",), k=3)
    assert top[0].section_id == "4F.17"


def test_page_labels_resolve_for_both_extractors():
    from trafficlegal.ingest import PAGE_MARKER, paged_lines

    top_label = "MUTCD 11th Edition\n\nPage 709\n\nSection 4F.18 Preemption"
    bottom_label = "Section 4F.17 Yellow Change\nlast line\nPage 708 MUTCD 11th Edition"
    lines = paged_lines(top_label + "\f" + bottom_label)
    markers = [line[len(PAGE_MARKER):] for line in lines if line.startswith(PAGE_MARKER)]
    assert markers == ["709", "708"]


def test_scraper_parses_article_parameter_groups():
    from trafficlegal.scraper import build_schema, parse_article

    html = ("<h1>Integrating HCS Signal Analyses with Excel</h1><ul>"
            "<li><strong>Intersection geometry</strong>: number of lanes, lane width, storage length, grade %;</li>"
            "<li><strong>Performance measures</strong>: control delay, LOS, and queue storage ratios.</li></ul>"
            "<p>forecast for 2023, 2030, and 2035</p>")
    article = parse_article(html)
    assert article["groups"]["Intersection geometry"][0] == "number of lanes"
    assert article["scenario_years"] == [2023, 2030, 2035]
    schema = build_schema(article)
    mapped = {m["parameter"]: m["columns"] for m in schema["parameter_mapping"]}
    assert "grade_pct" in mapped["grade %"] and "los" in mapped["LOS"]
