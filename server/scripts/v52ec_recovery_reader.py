"""Diagnostic-only S8 recovery. Pending review; not authorized for execution.

The original estimator remains unavailable. No pool or strength classification
is called. Caller must verify terminal process state and exclusive ownership.
"""
import copy
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path


ORIGINAL_SHA = '0c09f172876dfc934fe9f6765aaf3997dd6030071a3dc58effb257ed57e32f51'
PREDECLARATION_SHA = '72a2ed7ab64f1ae0f8e76cc043d90b771a23714c078b4e83916d0ccb6246debe'


def local_module(name):
    path = Path(__file__).with_name(name + '.py')
    if name == 'v52ec_reader' and hashlib.sha256(path.read_bytes()).hexdigest() != ORIGINAL_SHA:
        raise ValueError('original reader source drift')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyze(root, *, reservation, status, rc_path, support, reader_dir, primary_path, report):
    """Populate a caller-owned safe report, including progress before refusal.

    All shards pass through the original validator exactly once. Internal
    utilities/actions never enter report; caught failures disclose stage only.
    """
    old = local_module('v52ec_reader')
    diag = local_module('v52ec_recovery_diagnostics')
    rc = old.helper(rc_path)
    companion = rc.pinned(Path(support) / 'readout_with_health.py', rc.COMPANION_SHA)
    coverage = rc.pinned(Path(support) / 'play_trace_coverage.py', rc.COVERAGE_SHA)
    primary = rc.pinned(primary_path, rc.PRIMARY_SHA)
    root = Path(root)
    status_bytes = Path(status).read_bytes()
    report['stage'] = 'metadata_preflight'
    with companion.frozen_modules(reader_dir) as (validator, _health):
        load = validator._load
        templates, sha = load(old.CONFIGS)
        old.need(sha == old.CONFIG_SHA, 'config freeze drift')
        metadata = {old.CONFIGS: sha}
        metadata.update(old.check_lane(root=root, reservation=reservation, status=status, load=load))
        expected = {}
        for side, prefix in enumerate(old.PREFIXES):
            for seed in old.HOST_SEEDS['cloud']:
                config = copy.deepcopy(templates[side])
                config['seed0'] = seed
                expected[f'{prefix}-{seed}'] = config
        entries, checksums = old.preflight_paired_windows(root, expected,
            seeds=old.HOST_SEEDS['cloud'], prefixes=old.PREFIXES,
            clusters=old.CLUSTERS, validator=validator)
        metadata.update(checksums)
        report['metadata_sha256'] = {str(p): s for p, s in metadata.items()}
        fingerprints, audits, seen, cache = {}, {}, set(), {}

        def observe(path):
            raw = path.name.startswith('cluster-') and path.suffix == '.json'
            if raw:
                old.need(path not in seen and not path.is_symlink(), 'duplicate/symlinked shard')
                seen.add(path)
            shard, digest = load(path)
            if raw:
                cov = coverage.audit_play_trace_coverage(shard)
                audit = audits.setdefault(path.parent, dict(shards=0, covered=0,
                    expected_calls=0, recorded_calls=0))
                audit['shards'] += 1
                audit['covered'] += int(cov['covered'])
                audit['expected_calls'] += cov['expected_calls']
                audit['recorded_calls'] += cov['recorded_calls']
                report['trace_coverage'][path.parent.name] = dict(audit)
                fp = diag.trace_fingerprint(shard, coverage=cov)
                target = fingerprints.setdefault(path.parent, {})
                old.need(not set(target).intersection(fp), 'duplicate trace identity')
                target.update(fp)
            return shard, digest

        validator._load = observe
        primary.load = lambda folder: cache[Path(folder)]
        for seed, pair in entries:
            report['stage'] = 'raw_validation'
            report['active_seed'] = seed
            folders = [root / e['directory'] for e in pair]
            for entry, folder in zip(pair, folders):
                values, receipt = validator._arm(root, entry)
                cache[folder] = rc.cluster_sums(values, entry['config'])
                report['input_receipts'].append(receipt)
            report['stage'] = 'window_diagnostics'
            _delta, se, n = primary.window_delta(*folders)
            old.need(n == old.CLUSTERS, 'bootstrap population mismatch')
            numbers = diag.numeric_diagnostics(cache[folders[0]], cache[folders[1]],
                                               bootstrap_se=se, clusters=old.CLUSTERS)
            agreement = diag.trace_agreement(*(fingerprints[f] for f in folders))
            report['windows'].append(dict(seed0=seed, **numbers, **agreement))
            for folder in folders:
                del cache[folder], fingerprints[folder]
        report['stage'] = 'final_metadata_check'
        for path, sha in metadata.items():
            old.need(load(path)[1] == sha, 'metadata changed')
        old.need(Path(status).read_bytes() == status_bytes, 'terminal status changed')
        report['terminal_status_sha256'] = hashlib.sha256(status_bytes).hexdigest()
    report.pop('active_seed', None)
    report['stage'] = 'complete'


def run_once(output, **kwargs):
    """Claim before access; preserve safe diagnostics on validation failure.

    No exception text is serialized: dependency errors may contain values.
    A crash leaves the exclusive claim, preventing an automatic second read.
    """
    output = Path(output)
    old = local_module('v52ec_reader')
    old.helper(kwargs['rc_path']).claim_output(output)
    report = dict(schema='v52ec-recovery-diagnostics-v1',
                  predeclaration_sha256=PREDECLARATION_SHA,
                  original_primary='UNAVAILABLE', direction_suppressed=True,
                  outcome_blind=False, stage='source_validation',
                  windows=[], input_receipts=[], trace_coverage={})
    success = False
    try:
        analyze(report=report, **kwargs)
        success = True
    except (Exception, SystemExit):
        report['recovery_status'] = 'REFUSED'
    else:
        report['recovery_status'] = 'DIAGNOSTICS_COMPLETE'
    # Persist before returning a refusal to the caller. No estimator follows.
    with output.open('x') as handle:
        json.dump(report, handle, sort_keys=True, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    return success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    for flag in ('reservation', 'status', 'rc-path', 'support', 'reader-dir', 'primary-path'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = vars(parser.parse_args())
    output = args.pop('output')
    success = run_once(output, **args)
    print('DIAGNOSTICS_COMPLETE' if success else 'REFUSED: safe report preserved')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
