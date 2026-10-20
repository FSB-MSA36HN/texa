"""texa catalog publish|coverage · texa query <spec.json> · texa ask "<question>" """
import argparse
import json
import sys

from . import catalog, db


def main(argv=None):
    p = argparse.ArgumentParser(prog="texa")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog")
    c.add_argument("action", choices=["publish", "coverage", "check"])
    c.add_argument("path", nargs="?", default=str(db.CATALOG_PATH))
    q = sub.add_parser("query", help="run a QuerySpec JSON file without the LLM")
    q.add_argument("spec")
    a = sub.add_parser("ask", help="ask a question end to end")
    a.add_argument("question")
    a.add_argument("--model")
    a.add_argument("--answers", help='clarification answers as JSON, e.g. {"source": ["olist_marketplace"]}')
    args = p.parse_args(argv)
    db.migrate()

    if args.cmd == "catalog":
        if args.action == "publish":
            print(f"published catalog version {catalog.publish(args.path)}")
        elif args.action == "check":
            import yaml
            catalog.validate_catalog(yaml.safe_load(open(args.path, encoding="utf-8")))
            print("catalog is valid")
        else:
            cov = catalog.coverage(catalog.published(), catalog.load_sources(max_age=0))
            for sid, info in cov.items():
                print(f"\n{sid}: {info['metric_coverage']:.0%} of metrics answerable")
                for mid, reasons in info["metrics_missing"].items():
                    print(f"  - {mid}: {'; '.join(reasons)}")
                if info["dimensions_missing"]:
                    print(f"  dimensions without data: {', '.join(info['dimensions_missing'])}")
    elif args.cmd == "query":
        from .pipeline import run_spec
        out = run_spec(json.load(open(args.spec)))
        print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    elif args.cmd == "ask":
        from .answer import ask_cli
        out = ask_cli(args.question, model=args.model, answers=json.loads(args.answers) if args.answers else None)
        print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
