"""Reduce the corpus to one row per episode, and apply a predicate to it.

This script runs inside winnow's environment, not ours — winnow pins
`rerun-sdk==0.34.1` and `datafusion~=53.0`, which we do not want to constrain
the teleop environment with. `curation/pipeline.py` invokes it with the winnow
package on `PYTHONPATH` and `WINNOW_SRC` / `WINNOW_DATA` set.

It writes JSON to `--out` rather than stdout, because the catalog server logs to
stdout on its way up.
"""

import argparse
import json

from catalog import episode_metrics, open_corpus  # winnow, via PYTHONPATH


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--where", required=True, help="SQL predicate over the metrics columns")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open_corpus() as (client, dataset):
        frame = episode_metrics(client, dataset)
        client.ctx.register_view("metrics", frame)
        kept = client.ctx.sql(
            f"SELECT episode FROM metrics WHERE {args.where} ORDER BY episode"
        ).to_pandas()["episode"].tolist()
        rows = frame.to_pandas()

    with open(args.out, "w") as handle:
        # via to_json so numpy scalars and NaN survive the trip
        json.dump({"metrics": json.loads(rows.to_json(orient="records")), "kept": kept}, handle)

    print(f"{len(kept)} of {len(rows)} episodes satisfy: {args.where}")


if __name__ == "__main__":
    main()
