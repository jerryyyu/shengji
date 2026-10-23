"""Recipe admission after authorized input binding, before statistical reduction."""
from shengji.train.cwv_shortlist_screen import validate_shard
from shengji.train.screen_deadline import RECIPE as DEADLINE_RECIPE
from window_plan import CLUSTERS


def admit_records(plan, expected_configs, configs, shards):
    """Validate every window before returning any outcome records.

    This performs no IO. A sealed reader must bind source, seals, reservation
    and terminal before supplying these objects, then check scientific validity.
    Expected configs must come from the reviewed packet, never from the outputs.
    """
    outputs = [w['output'] for w in plan['windows']]
    if (len(outputs) != 20 or len(set(outputs)) != 20
            or any(set(mapping) != set(outputs) for mapping in (expected_configs, configs, shards))):
        raise ValueError('window inventory drift')
    records = {}
    for window in plan['windows']:
        output = window['output']
        config = configs[output]
        if config != expected_configs[output]:
            raise ValueError('frozen config drift')
        arm = plan['arms'][window['side']]
        expected = dict(arm='policy', arm_policy=arm['name'],
                        arm_policy_identity=arm['identity'], baseline='production',
                        clusters=CLUSTERS, seed0=window['seed'],
                        trump_ranks=window['ranks'].split(','), decision_deadline=DEADLINE_RECIPE)
        if (any(config.get(k) != v for k, v in expected.items())
                or config.get('round_kind', 'first') != window['round_kind']):
            raise ValueError('plan/config drift')
        by_cluster = {}
        for shard in shards[output]:
            cluster = shard.get('cluster')
            if (type(cluster) is not int or not 0 <= cluster < CLUSTERS
                    or cluster in by_cluster):
                raise ValueError('duplicate or invalid shard cluster')
            by_cluster[cluster] = validate_shard(shard, config, cluster)
        if len(by_cluster) != CLUSTERS:
            raise ValueError('incomplete shard window')
        records[output] = [row for cluster in range(CLUSTERS)
                           for row in by_cluster[cluster]['records']]
    return records
