"""Generate an outcome-blind v53dts instance of the pinned v52 reader.

No outcome access. Descriptive counters are embedded so the reviewed reader
does not import mutable project code at raw-read time.
"""
import ast
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_SHA = '0c09f172876dfc934fe9f6765aaf3997dd6030071a3dc58effb257ed57e32f51'


def build():
    raw = (HERE / 'v52ec_reader.py').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BASE_SHA
    source = raw.decode()
    substitutions = {
        'v52ec': 'v53dts',
        '52060910, 52160910, 52260910, 52360910, 52460910':
            '53060910, 53160910, 53260910, 53360910, 53460910',
        'PVSEARCH-r38rcec': 'PVSEARCH-r38dts',
        'pv-search-491ee4bf-w64-k8-div-rc-rcec-tb-la-r3950772a-bury-hybrid-ad86d3fafbbd':
            'pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-r0f40c8b5-bury-hybrid-273fed4cd40d',
        'd44880a86210dda9d55cb4992ef87a4bfbd8e821ff14af7b7f1881f9d1f030c4':
            'b9e107dfd65005e1c3346ee398c868773f4fbed205d21387f11d77028a99f6e6',
        'c177d5f51ed1bc79fbb24365fe3761e919a3054953a27dfa1832fd80f3df6ce2':
            'c04c5a9fecaf6e40fff73635c6e0eccdb9e76113c8af43920439128801eb0a9c',
        'd65a5c9e3927c6cad47ff4fdea79904c2775afb9111d0b6dcb30e74928eb572e':
            '601a6406e662fc9878d7cd294896947508549ba34e2c7934526879200bc79fb1',
        '3ab67ae299b82d72c7edfeca8d86477ea15bc72aa8e9290a65fcd49364bf65bd':
            '56983dbcce50c2e6dd3d41d31a61b5126d6f3b5d587bae9171244ba74057ac83',
        'event-complete refusal history versus release38':
            'doomed-throw swap versus release38',
        'activations=empty_activations()': 'doomed_throw=empty_doomed_throw_census()',
        "observe_activations(item['activations'], shard)":
            "observe_doomed_throw(item['doomed_throw'], shard, "
            "candidate=path.parent.name.startswith(PREFIXES[0] + '-'))",
    }
    for old, new in substitutions.items():
        assert old in source, old
        source = source.replace(old, new)
    start = source.index('        activation_by_arm = {}')
    stop = source.index("        result = dict(schema=", start)
    source = source[:start] + '''        for item in census.values():
            item['doomed_throw_summary'] = summarize_doomed_throw([item['doomed_throw']])
        mechanism_by_arm = {
            side: summarize_doomed_throw(
                item['doomed_throw'] for folder, item in census.items()
                if Path(folder).name.startswith(prefix + '-'))
            for side, prefix in zip(('candidate', 'comparator'), PREFIXES)}
''' + source[stop:]
    start = source.index('            activation=dict(')
    stop = source.index('            primary_analyzer_sha256=', start)
    source = source[:start] + '''            doomed_throw_mechanism=dict(by_arm=mechanism_by_arm,
                note='DESCRIPTIVE ONLY; per-window counters in descriptive_health; '
                     'unaligned rounds excluded, never imputed; no strength attribution'),
''' + source[stop:]
    # Embed the complete pure helper (including its own imports/constants).
    helper = (HERE.parent / 'shengji/eval/doomed_throw_readout.py').read_text()
    tree = ast.parse(helper)
    helper = '\n\n'.join(ast.get_source_segment(helper, node) for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module == '__future__'))
    source = source.replace('def analyze(', helper + '\n\ndef analyze(', 1)
    compile(source, 'v53dts_reader.py', 'exec')
    return source


if __name__ == '__main__':
    print(build(), end='')
