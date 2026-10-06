"""Immutable completed S11 roots; no retry, model loading or launch authority.

The outer collector owns its predeclared schedule/refusal policy. Missing
completion is not permission to retry a root whose computation was started.
An exclusive run owner is still required; publication refuses overwrite.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .s11_report import summarize_s11
from ..luna.atomic_io import partial_path, publish_exclusive_bytes

_FIELDS = set('schema root_id seed fill_seed recipe encoder_version tape_receipt '
              'worlds policy_capture value_capture report legal_count legal_complete '
              'pool_scope provenance_verified model_verified serving_choice_assessed'.split())


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _context(packet_sha256, fixture, seed, fill_seed):
    if type(packet_sha256) is not str or not re.fullmatch('[0-9a-f]{64}', packet_sha256):
        raise ValueError('packet SHA256 required')
    if any(type(n) is not int or n < 0 for n in (seed, fill_seed)):
        raise ValueError('nonnegative integer seeds required')
    if type(fixture.id) is not str or not fixture.id:
        raise ValueError('root id required')
    return dict(packet_sha256=packet_sha256, root_id=fixture.id,
                fixture_sha256=hashlib.sha256(_encode(fixture.to_json())).hexdigest(),
                seed=seed, fill_seed=fill_seed)


def _validate(result, context):
    if (not isinstance(result, dict) or set(result) != _FIELDS
            or result.get('schema') != 's11-collected-root-v1'):
        raise ValueError('completed S11 root required')
    for key in ('root_id', 'seed', 'fill_seed'):
        if type(result.get(key)) is not type(context[key]) or result[key] != context[key]:
            raise ValueError(f'collected root {key} mismatch')
    if result.get('model_verified') is not False or result.get('provenance_verified') is not False:
        raise ValueError('persistence does not establish model or provenance authority')
    report = result.get('report')
    if not isinstance(report, dict) or report.get('status') != 'valid':
        raise ValueError('completed valid report required')
    if (result['pool_scope'] != 'release38 capped served pool'
            or result['serving_choice_assessed'] is not False
            or type(result['legal_count']) is not int or result['legal_count'] < 1
            or type(result['legal_complete']) is not bool
            or type(result['encoder_version']) is not int
            or not isinstance(result['recipe'], dict)
            or type(result['worlds']) is not list or len(result['worlds']) != 64):
        raise ValueError('collected root metadata mismatch')
    receipt, policy, value = (result[k] for k in ('tape_receipt', 'policy_capture', 'value_capture'))
    for capture, schema in ((receipt, 'public-refusal-tape-v1'),
                            (policy, 'fixed-tape-policy-ranks-v1'),
                            (value, 'fixed-tape-same-leaf-capture-v1')):
        if (not isinstance(capture, dict) or capture.get('schema') != schema
                or type(capture.get('world_count')) is not int or capture['world_count'] != 64):
            raise ValueError('collected root capture mismatch')
    if (receipt.get('seed') != context['seed'] or receipt.get('fill_seed') != context['fill_seed']
            or receipt.get('mode') != 'history-primed'
            or receipt.get('checkpoint_sha256') != result['recipe'].get('checkpoint_sha256')
            or policy.get('encoder_version') != result['encoder_version']
            or policy.get('actions') != value.get('actions')
            or policy.get('actions') != report.get('baseline', {}).get('actions')):
        raise ValueError('collected root capture linkage mismatch')
    actions = policy['actions']
    if not isinstance(actions, list) or not actions:
        raise ValueError('collected root actions missing')
    for key in ('value_matrix', 'signed_trick_points'):
        matrix = value.get(key)
        if (not isinstance(matrix, list) or len(matrix) != 64
                or any(not isinstance(row, list) or len(row) != len(actions) for row in matrix)):
            raise ValueError('collected root value matrix mismatch')
    if len(value.get('serving_value_means', [])) != len(actions):
        raise ValueError('collected root value means mismatch')
    recipe = result['recipe']
    config, effective = recipe.get('config'), recipe.get('effective')
    if (set(recipe) != {'config', 'effective', 'checkpoint_sha256'}
            or not isinstance(config, dict) or not isinstance(effective, dict)
            or set(effective) != {'worlds', 'cap', 'batch_size', 'candidates'}
            or any(type(v) is not int or v < 1 or config.get(k) != v
                   for k, v in effective.items())
            or config.get('checkpoint_sha256') != recipe['checkpoint_sha256']):
        raise ValueError('collected root recipe mismatch')
    baseline = report['baseline']
    if (baseline.get('legal_count') != result['legal_count']
            or baseline.get('legal_complete') is not result['legal_complete']
            or (result['legal_complete'] and result['legal_count'] != len(actions))):
        raise ValueError('collected root legal metadata mismatch')
    # Use the existing real consumer contract, including JSON-normalized types.
    summarize_s11([report], [context['root_id']], bootstrap_samples=1)


def save_s11_root(path, result, *, packet_sha256, fixture):
    """Publish a completed capture once; existing output is never replaced.

    The packet digest binds the caller's reviewed source/model recipe. It is
    an identity, not proof that that recipe or the fixture was authorized.
    Parent directories must already exist under the run owner's control.
    """
    if not isinstance(result, dict):
        raise ValueError('completed S11 root required')
    context = _context(packet_sha256, fixture, result.get('seed'), result.get('fill_seed'))
    _validate(result, context)
    payload = dict(schema='s11-saved-root-v1', context=context, result=result)
    encoded = _encode(payload)
    envelope = _encode(dict(payload=payload, sha256=hashlib.sha256(encoded).hexdigest())) + b'\n'
    publish_exclusive_bytes(Path(path), envelope)


def load_s11_root(path, *, packet_sha256, fixture, seed, fill_seed=0):
    """Reuse a matching completion; None only for an absent completion file.

    Corruption, incompatible input/packet and special files fail closed. This
    function performs no sampling, inference, reconstruction or auto-repair.
    """
    context = _context(packet_sha256, fixture, seed, fill_seed)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        staged = partial_path(Path(path))
        if staged.exists() or staged.is_symlink():
            raise ValueError('interrupted publication requires explicit recovery')
        return None
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o400 or before.st_nlink not in (1, 2)):
            raise ValueError('immutable completion identity mismatch')
        if before.st_nlink == 2:
            # The only permitted second link is the publisher's crash residue.
            staged = partial_path(Path(path)).stat(follow_symlinks=False)
            if (staged.st_dev, staged.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError('completion link identity mismatch')
        envelope = json.load(stream)
        after = os.fstat(stream.fileno())
        if any(getattr(before, key) != getattr(after, key) for key in
               ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink', 'st_mode', 'st_uid')):
            raise ValueError('completion changed during read')
    if not isinstance(envelope, dict) or set(envelope) != {'payload', 'sha256'}:
        raise ValueError('saved root envelope mismatch')
    payload = envelope['payload']
    if hashlib.sha256(_encode(payload)).hexdigest() != envelope['sha256']:
        raise ValueError('saved root SHA256 mismatch')
    if (not isinstance(payload, dict) or set(payload) != {'schema', 'context', 'result'}
            or payload['schema'] != 's11-saved-root-v1' or payload['context'] != context):
        raise ValueError('saved root context mismatch')
    _validate(payload['result'], context)
    return payload['result']
