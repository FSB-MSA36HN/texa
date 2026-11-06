"""Run a bounded real-model check without putting credentials in env, Git or logs.

Credentials JSON must be ignored by Git, owner-readable only, and under .runtime.
This command uses gateway-reported pricing and pessimistic per-call reservations.
It wraps the existing evaluator; it does not replace model output or expected gold.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from benchmark import ROOT
from gateway_budget import configure_gateway_from_environment, update_ledger, validate_credentials_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True)
    parser.add_argument('--ledger', default=str(ROOT / '.runtime/gateway-cost-ledger.json'))
    parser.add_argument('--runner', choices=('benchmark', 'ablation', 'accuracy'), default='benchmark')
    args, forwarded = parser.parse_known_args()
    path = validate_credentials_path(Path(args.credentials), ROOT / '.runtime')
    secret = json.loads(path.read_text())
    model, base_url = secret['model'], secret['base_url']
    if not 0 < secret['max_usd'] <= 20:
        raise ValueError('This validation wrapper is capped at the authorized 20 USD')
    import httpx
    try:
        response = httpx.get(base_url.removesuffix('/v1') + '/model/info',
            headers={'Authorization': 'Bearer ' + secret['api_key']}, timeout=20)
        response.raise_for_status()
        info = next(row['model_info'] for row in response.json()['data'] if row['model_name'] == model)
        input_price, output_price = float(info['input_cost_per_token']), float(info['output_cost_per_token'])
    except Exception:
        raise ValueError('Could not verify gateway model pricing; check the configured model and gateway privately') from None
    if input_price <= 0 or output_price <= 0:
        raise ValueError('Gateway must provide positive model prices before running')
    ledger_path = Path(args.ledger).resolve()
    ledger_path.relative_to(ROOT / '.runtime')
    def update(reserve=0, release=0, actual=0, usage=None):
        return update_ledger(ledger_path, ledger_path.with_suffix('.lock'), model=model,
            input_price=input_price, output_price=output_price, max_usd=secret['max_usd'],
            reserve=reserve, release=release, actual=actual, usage=usage)

    from texa import llm
    # Children launched by --matrix inherit only protected paths and pricing;
    # the API key remains in the chmod-600 runtime file, never in env/logs.
    budget_env = {
        'TEXA_GATEWAY_BUDGET_CREDENTIALS': str(path),
        'TEXA_GATEWAY_BUDGET_LEDGER': str(ledger_path),
        'TEXA_GATEWAY_INPUT_PRICE': str(input_price),
        'TEXA_GATEWAY_OUTPUT_PRICE': str(output_price),
        'TEXA_GATEWAY_MAX_USD': str(secret['max_usd']),
    }
    old_env = {key: os.environ.get(key) for key in budget_env}
    os.environ.update(budget_env)
    previous_guard = llm.REQUEST_GUARD
    llm._openai_client = lambda key, url: __import__('openai').OpenAI(
        api_key=key, base_url=url, timeout=llm.TIMEOUT_S, max_retries=0)
    configure_gateway_from_environment(ROOT / '.runtime')
    if '--model' in forwarded:
        raise ValueError('Model comes from the protected credentials file')
    forwarded += ['--model', model]
    sys.argv = [sys.argv[0], *forwarded]
    try:
        if args.runner == 'benchmark':
            import run_benchmark
            run_benchmark.main()
        else:
            if args.runner == 'accuracy':
                import run_accuracy_study
                code = run_accuracy_study.main()
            else:
                import run_ablation
                code = run_ablation.main()
            if code:
                raise SystemExit(code)
    finally:
        llm.REQUEST_GUARD = previous_guard
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        totals = update()
        print(json.dumps({'gateway_check_budget': {k:totals[k] for k in (
            'model','calls','input_tokens','output_tokens','spent_estimated_usd','reserved_usd','max_usd')}}), flush=True)


if __name__ == '__main__':
    main()
