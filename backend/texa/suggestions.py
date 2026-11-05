"""Suggestions are validated semantic intents, never unchecked model prose."""
from .catalog import display_label
from .sanity import check_availability
from .spec import SpecError, validate_spec


def suggestions(cat, sources, scope=None, lang='vi', limit=4):
    selected = [sid for sid in (scope or sources) if sid in sources]
    out = []
    for sid in selected:
        src = sources[sid]
        for metric in cat.metrics:
            raw = {'contract_version': cat.contract_version, 'source_ids': [sid], 'shape': 'aggregate',
                   'selection': [], 'recipe': metric.id, 'metrics': [], 'filters': [], 'time_range': {'kind': 'all'}}
            try:
                spec = validate_spec(raw, cat, sources)
                check_availability(spec, cat, sources)
            except SpecError:
                continue
            question = (f'{display_label(metric, lang)} của {src.label}, toàn bộ dữ liệu' if lang.startswith('vi') else
                        f'{display_label(metric, lang)} for {src.label}, all available data')
            out.append({'question': question, 'source_id': sid, 'spec': spec.model_dump(mode='json'),
                        'catalog_version': cat.contract_version})
    # Round robin across sources so onboarding exposes both datasets.
    out.sort(key=lambda v: (next(i for i, m in enumerate(cat.metrics) if m.id == v['spec']['recipe']),
                            selected.index(v['source_id'])))
    return out[:limit]


def questions(cat, sources, scope=None, lang='vi', limit=3):
    return [s['question'] for s in suggestions(cat, sources, scope, lang, limit)]
