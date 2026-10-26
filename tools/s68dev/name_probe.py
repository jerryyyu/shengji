"""s68dev name / config probe (local, no games): through the PINNED s66 adapter (beside the harness, as staged) on the candidate tree,
derive the defender and each arm's exploiter exactly as the lane will (the adapter's variant_factory over the arm's --exploiter-env
words, parsed by the harness's _parse_env), and print names, classes, the config diff against the defender and the time settings.
Usage: FIND_GAPS_SERVER=<tree>/server FIND_GAPS_PKG=<smv3out> FIND_GAPS_PATH_MAP=/data/models/s58-e6-42444515.npz=<s58> SHENGJI_FAST=1 \
       python -B name_probe.py <adapter path> 'ARM WORD WORD ...;ARM WORD ...'"""
import dataclasses, importlib.util, json, sys
adapter, specs = sys.argv[1:3]
sys.path.insert(0, adapter.rsplit('/', 1)[0])
spec = importlib.util.spec_from_file_location('s66_sc8_adapter', adapter); A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
m = A.D
cfg = lambda b: dataclasses.asdict(b.config)
dn, dmake = A.variant_factory(()); db = dmake(7)
attrs = ('serving_budget_seconds', 'leaf_greedy_deadline_ms', 'bury_serving_budget_seconds', 'worlds', 'candidates', 'belief_capacity',
         'encode_prefix_cache', 'leaf_greedy_stream', 'encode_batch_fast', 'single_candidate_fast', 'exact_lead_max_seconds')
out = {'defender': dn, 'defender_class': type(db).__name__, 'defender_attrs': {a: getattr(db, a, None) for a in attrs}}
for item in filter(None, specs.split(';')):
    arm, *words = item.split()
    eenv = m._parse_env(words)
    en, emake = A.variant_factory(eenv); eb = emake(7)
    diff = sorted(x for x in set(cfg(db)) | set(cfg(eb)) if cfg(db).get(x) != cfg(eb).get(x))
    out[arm] = {'exploiter_env': [list(x) for x in eenv], 'name': en, 'policy_name': eb.policy_name, 'class': type(eb).__name__,
                'mro': [c.__name__ for c in type(eb).__mro__][:4], 'config_diff': {x: [cfg(db).get(x), cfg(eb).get(x)] for x in diff},
                'attrs': {a: getattr(eb, a, None) for a in attrs},
                'belief_proposal': __import__('shengji.train.pv_search_policy', fromlist=['x']).recipe_payload(eb.config)['belief_worlds_package']['proposal']}
print(json.dumps(out, indent=1, default=str))
