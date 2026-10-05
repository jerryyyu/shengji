"""Narrow retained-panel access, not a scientific readout or launch gate.

Caller must authenticate source/runtime, the exact file pins and terminal seal,
and obtain exclusive permitted read ownership before calling. No sampling,
prediction, full readout or publication occurs here. The selected record's
cached summaries are recomputed only to validate them. Fixture/model/
encoder and refusal semantics still need independent checks before rank use.
"""
import copy
import hashlib

from . import observation_queue as guards
from .m9_panel_plan import build_m9_panel_plan
from .m9_panel_readout import _read_panel, validate_panel_completion


MAX_FILE_BYTES = 16 * 1024 * 1024
META = ('packet', 'owner', 'process', 'collection', 'saved_readout', 'plan')


def read_selected_panel(files, *, packet_sha256, index):
    """Read six bound metadata files and exactly one ordered panel snapshot.

    Index is the original fifteen-job plan position, not a filter over results.
    Checksums authenticate supplied bytes, not the authority of supplied pins.
    """
    guards._strict_sha(packet_sha256, 'packet SHA')
    if type(index) is not int or not 0 <= index < 15:
        raise ValueError('strict panel index in [0, 15) required')
    spec = copy.deepcopy(files)
    if type(spec) is not dict or set(spec) != set(META) | {'panel'}:
        raise ValueError('exact selected-panel input pins required')
    paths = {}
    for name, pin in spec.items():
        if type(pin) is not dict or set(pin) != {'path', 'sha256'}:
            raise ValueError('exact path/SHA pin required')
        guards._strict_sha(pin['sha256'], name)
        paths[name] = guards._canonical_absolute(pin['path'], name)
    if len(set(paths.values())) != len(paths):
        raise ValueError('distinct input paths required')
    if spec['packet']['sha256'] != packet_sha256:
        raise ValueError('packet pin mismatch')
    hashes = {}

    def read(name):
        raw, _ = guards._stable_read(paths[name], MAX_FILE_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != spec[name]['sha256']:
            raise ValueError(f'input SHA mismatch: {name}')
        hashes[name] = digest
        return guards._parse_finite_object(raw.decode('utf-8'))

    packet = read('packet')
    if packet.get('schema') != 'm9-panel-admission-v1':
        raise ValueError('M9 collection packet required')
    recipe = packet.get('recipe')
    if type(recipe) is not dict:
        raise ValueError('collection recipe required')
    output = guards._canonical_absolute(recipe.get('output_dir'), 'output')
    evidence = guards._canonical_absolute(recipe.get('evidence'), 'evidence')
    expected = {
        'owner': guards._canonical_absolute(packet.get('status'), 'status'),
        'process': evidence / 'process.json', 'collection': output / 'terminal.json',
        'saved_readout': guards._canonical_absolute(recipe.get('saved_readout'), 'saved'),
        'plan': output / 'plan.json', 'panel': output / f'validated-{index:03d}.json',
    }
    if any(paths[name] != path for name, path in expected.items()):
        raise ValueError('input path not bound to collection packet')
    if spec['saved_readout']['sha256'] != recipe.get('saved_readout_sha256'):
        raise ValueError('saved readout pin not bound to recipe')
    metadata = {name: read(name) for name in META[1:]}
    validate_panel_completion(metadata['owner'], metadata['process'],
                              metadata['collection'], packet_sha256=packet_sha256)
    saved = metadata['saved_readout']
    if (set(saved) != {'analysis', 'provenance'}
            or type(saved['analysis']) is not dict or type(saved['provenance']) is not dict):
        raise ValueError('saved analysis/provenance required')
    jobs = build_m9_panel_plan(saved['analysis'])
    plan = {'schema': 'm9-panel-attempt-v1', 'jobs': jobs,
            'analysis_sha256': hashlib.sha256(guards._canonical(saved['analysis'])).hexdigest(),
            'provenance_verified': False}
    if guards._canonical(metadata['plan']) != guards._canonical(plan):
        raise ValueError('published plan differs from saved analysis')
    record = read('panel')
    job = jobs[index]
    if (set(record) != {'job', 'panel', 'replay_consistency', 'validation_status',
                       'replay_failure', 'ledger_cadence'}
            or record.get('validation_status') != 'passed' or record.get('replay_failure') is not None
            or guards._canonical(record.get('job')) != guards._canonical(job)):
        raise ValueError('selected record validation or job mismatch')
    cadence = 'fresh-root' if job['mode'] == 'fresh-root' else 'single-seat-actor-turns'
    if record['ledger_cadence'] != cadence:
        raise ValueError('selected record ledger cadence mismatch')
    # Validate every saved capture and cached replay exposed to S10 consumers,
    # including full-pool means/points and batch partition. This has no I/O or
    # prediction and does not invoke the fifteen-panel readout/diagnostic views.
    _read_panel(record, job, saved['analysis'])
    panel = record['panel']
    return {'schema': 'selected-m9-panel-v1', 'index': index,
            'job': copy.deepcopy(job), 'panel': copy.deepcopy(panel),
            'input_sha256': hashes, 'packet_sha256': packet_sha256,
            'provenance_verified': False, 'serving_choice_assessed': False}
