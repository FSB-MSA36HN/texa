"""Run a bounded real-model check without putting credentials in env, Git or logs.

Credentials JSON must be ignored by Git, owner-readable only, and under .runtime.
This command uses gateway-reported pricing and pessimistic per-call reservations.
It wraps the existing evaluator; it does not replace model output or expected gold.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark import ROOT
from gateway_budget import update_ledger, validate_credentials_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True)
    parser.add_argument('--ledger', default=str(ROOT / '.runtime/gateway-cost-ledger.json'))
    parser.add_argument('--runner', choices=('benchmark', 'ablation'), default='benchmark')
    args, forwarded = parser.parse_known_args()
    path = validate_credentials_path(Path(args.credentials), ROOT / '.runtime')
    secret = json.loads(path.read_text())
    model, base_url = secret['model'], secret['base_url']
    if not 0 < secret['max_usd'] <= 10:
        raise ValueError('This validation wrapper is capped at the authorized 10 USD')
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
    # The connection is supplied in memory only. Do not save a model connection
    # in the benchmark DB or log encrypted/plain credentials anywhere else.
    conn = {'provider': 'openai', 'api_key': secret['api_key'], 'base_url': base_url,
            'allowed_models': [model], 'default_model': model, 'max_output_tokens': 4096,
            'daily_token_limit': 0, 'answer_language': 'auto'}
    llm.get_connection = lambda with_key=False: dict(conn) if with_key else {k:v for k,v in conn.items() if k != 'api_key'}
    import openai
    llm._openai_client = lambda key, url: openai.OpenAI(api_key=key, base_url=url, timeout=60, max_retries=0)
    original = llm._CALLS['openai']

    def measured(connection, selected_model, system, prompt, schema, name, max_tokens):
        if selected_model != model:
            raise ValueError('Only the authorized model can be used')
        # UTF-8 bytes exceed ordinary token counts; reserve two HTTP calls for
        # the existing strict-schema -> JSON fallback, plus generous overhead.
        bytes_count = len((system + prompt + json.dumps(schema)).encode()) + 8192
        reservation = 2 * (bytes_count * input_price + max_tokens * output_price)
        update(reserve=reservation)
        try:
            text, usage, finish = original(connection, selected_model, system, prompt, schema, name, max_tokens)
            if usage[0] is None or usage[2] is None:
                raise ValueError('Missing usage; retained conservative cost reservation')
            cost = usage[0]*input_price + usage[2]*output_price  # no cache discount assumed
            update(release=reservation, actual=cost, usage=usage)
            return text, usage, finish
        except Exception:
            # Retain reservation for failed/unknown requests; never release an
            # uncertain provider charge or print a raw provider error with keys.
            raise llm.LLMError('GATEWAY_CHECK_FAILED', 'Gateway check failed; conservative budget reservation retained') from None

    llm._CALLS['openai'] = measured
    if '--model' in forwarded:
        raise ValueError('Model comes from the protected credentials file')
    forwarded += ['--model', model]
    sys.argv = [sys.argv[0], *forwarded]
    try:
        if args.runner == 'benchmark':
            import run_benchmark
            run_benchmark.main()
        else:
            import run_ablation
            code = run_ablation.main()
            if code:
                raise SystemExit(code)
    finally:
        totals = update()
        print(json.dumps({'gateway_check_budget': {k:totals[k] for k in (
            'model','calls','input_tokens','output_tokens','spent_estimated_usd','reserved_usd','max_usd')}}), flush=True)


if __name__ == '__main__':
    main()
