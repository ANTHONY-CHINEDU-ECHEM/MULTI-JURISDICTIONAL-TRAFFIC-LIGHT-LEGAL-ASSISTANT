"""Command line interface.

Arguments use a plain key=value form, for example:

    python run.py setup
    python run.py generate intersections=170 crashes=520 seed=20260930
    python run.py evaluate CR00017
    python run.py ask "Did the yellow interval meet requirements in crash CR00017?"
    python run.py serve port=8000
"""

import json
import sys

USAGE = """Multi Jurisdictional Traffic Light Incident Legal Assistant

Commands
  setup                     scrape, generate, excel, ingest and builddb in one step
  scrape                    scrape the McTrans article schema (offline snapshot fallback)
  generate                  build every dataset   [intersections=170 crashes=520 seed=20260930]
  excel                     write the HCS style Excel workbook to data/processed
  ingest                    parse the knowledge base into the hierarchical index
  builddb                   load the CSV tables into SQLite
  crashes                   list crashes          [limit=20 intersection=INT0001]
  evaluate CRASH_ID         run the millisecond evaluation and write the memo
  ask "QUESTION"            route a free text question (crash, intersection, time or regulation)
  retrieve "QUERY"          hierarchical retrieval only [state=AV jurisdiction=RIV k=8]
  sql "SELECT ..."          read only SQL against the structured store
  benchmark                 verdict accuracy and retrieval quality
  serve                     start the HTTP API    [host=127.0.0.1 port=8000]
"""


def _options(args):
    opts, positional = {}, []
    for arg in args:
        if "=" in arg and not arg.lower().startswith(("select", "with")):
            key, value = arg.split("=", 1)
            opts[key.strip().lower()] = value.strip()
        else:
            positional.append(arg)
    return opts, positional


def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("help", "h", "?"):
        print(USAGE)
        return 0
    command, rest = argv[0].lower(), argv[1:]
    opts, positional = _options(rest)

    if command in ("scrape", "setup"):
        from .scraper import scrape_and_save

        schema = scrape_and_save()
        print("Schema: " + str(len(schema["parameter_mapping"])) + " scraped parameters mapped to dataset columns")
    if command in ("generate", "setup"):
        from .synth import generate

        counts = generate(int(opts.get("intersections", 170)), int(opts.get("crashes", 520)),
                          int(opts.get("seed", 20260930)))
        _print(counts)
    if command in ("excel", "setup"):
        from .synth import export_excel

        print("Workbook: " + str(export_excel()))
    if command in ("ingest", "setup"):
        from .ingest import build_index

        docs = build_index()
        print("Indexed " + str(len(docs)) + " documents")
    if command in ("builddb", "setup"):
        from .store import build_database

        print("Database: " + str(build_database()))
    if command in ("scrape", "generate", "excel", "ingest", "builddb", "setup"):
        return 0

    if command == "crashes":
        from .store import StructuredRetriever

        rows = StructuredRetriever().crashes(int(opts.get("limit", 20)), opts.get("intersection"))
        for r in rows:
            print(r["crash_id"], r["crash_stamp"], r["intersection_id"], r["jurisdiction_code"], "phase",
                  r["subject_phase"], r["crash_type"])
        return 0
    if command == "evaluate":
        if not positional:
            print("evaluate needs a crash id, for example: python run.py evaluate CR00017")
            return 2
        from .assistant import LegalAssistant

        out = LegalAssistant().crash_report(positional[0].upper())
        print(out["answer_markdown"])
        print("\nReports: " + ", ".join(out["report_paths"]))
        return 0
    if command == "ask":
        from .assistant import LegalAssistant

        out = LegalAssistant().ask(" ".join(positional))
        print(out["answer_markdown"])
        return 0
    if command == "retrieve":
        from .retriever import HierarchicalRetriever

        results = HierarchicalRetriever().retrieve(" ".join(positional), state_code=opts.get("state"),
                                                   jurisdiction_code=opts.get("jurisdiction"),
                                                   k=int(opts.get("k", 8)))
        for r in results:
            print(round(r.score, 3), r.cite())
            print("   " + r.text[:240])
        return 0
    if command == "sql":
        from .store import StructuredRetriever

        _print(StructuredRetriever().query(" ".join(positional), limit=int(opts.get("limit", 200))))
        return 0
    if command == "benchmark":
        from .benchmark import run_all

        report = run_all()
        v, r = report["verdicts"], report["retrieval"]
        print("Verdict accuracy " + str(v["accuracy"]) + " over " + str(v["crashes"]) + " crashes; by confidence "
              + json.dumps(v["accuracy_by_confidence"]) + "; high confidence share " + str(v["high_confidence_share"]))
        for label, stats in v["per_class"].items():
            print("  " + label.ljust(36) + " support " + str(stats["support"]).rjust(4) + "  precision "
                  + str(stats["precision"]) + "  recall " + str(stats["recall"]))
        print("Retrieval hit@1 " + str(r["hit_at_1"]) + ", hit@3 " + str(r["hit_at_3"]) + ", MRR " + str(r["mrr"])
              + " over " + str(r["questions"]) + " questions")
        return 0
    if command == "serve":
        import uvicorn

        uvicorn.run("trafficlegal.api:app", host=opts.get("host", "127.0.0.1"), port=int(opts.get("port", 8000)))
        return 0
    print("Unknown command " + command + "\n\n" + USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
