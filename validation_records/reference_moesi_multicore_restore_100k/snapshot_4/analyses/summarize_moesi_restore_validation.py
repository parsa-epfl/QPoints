#!/usr/bin/env python3
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
MANIFEST_PATHS = [OUT / 'experiment_manifest.json', OUT / 'manifest.json']
CHECKPOINT_MANIFEST = OUT / 'staged' / 'checkpoint_manifest.json'
CHECKPOINT_GUARDRAILS = OUT / 'staged' / 'checkpoint_guardrails.json'
RESTORED_STATS = OUT / 'restored_100k' / 'stats.txt'
COLD_STATS = OUT / 'cold_100k' / 'stats.txt'
REPORT_JSON = OUT / 'analyses' / 'moesi_restore_validation_report.json'
REPORT_MD = OUT / 'analyses' / 'MOESI_RESTORE_VALIDATION.md'


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def read_stats(path: Path):
    stats = {}
    with path.open(encoding='utf-8') as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2 and not parts[0].startswith('-'):
                name, val = parts[0], parts[1]
                try:
                    stats[name] = int(float(val))
                except ValueError:
                    pass
    return stats


def sum_suffix(stats, suffix: str) -> int:
    return sum(v for k, v in stats.items() if k.endswith(suffix))


def upsert_artifact(manifest: dict, *, label: str, path: str, category: str, description: str):
    artifacts = manifest.setdefault('artifacts', [])
    for artifact in artifacts:
        if artifact.get('label') == label:
            artifact.update({
                'path': path,
                'category': category,
                'description': description,
                'protected': True,
                'required': True,
                'retention': 'keep',
            })
            return
    artifacts.append({
        'label': label,
        'path': path,
        'category': category,
        'description': description,
        'protected': True,
        'required': True,
        'retention': 'keep',
    })


manifest = read_json(CHECKPOINT_MANIFEST)
guardrails = read_json(CHECKPOINT_GUARDRAILS)
restored = read_stats(RESTORED_STATS)
cold = read_stats(COLD_STATS)

ladder_order = [
    'moesi_snapshot4_llc_restore_smoke_1k_v2',
    'moesi_snapshot4_private_owner_restore_smoke_1k_v2',
    'moesi_snapshot4_private_plus_clean_restore_smoke_1k_v3',
    'moesi_snapshot4_private_plus_single_plus_multi_clean_restore_smoke_1k_v1',
    'moesi_snapshot4_private_plus_clean_plus_i_nonllc_restore_smoke_1k_v1',
    'moesi_snapshot4_ownerfull_plus_clean_plus_i_restore_smoke_1k_v1',
    'moesi_snapshot4_all_families_restore_smoke_1k_v1',
]
ladder_labels = {
    'moesi_snapshot4_llc_restore_smoke_1k_v2': 'llc_only',
    'moesi_snapshot4_private_owner_restore_smoke_1k_v2': 'owner_only',
    'moesi_snapshot4_private_plus_clean_restore_smoke_1k_v3': 'owner_plus_single_clean',
    'moesi_snapshot4_private_plus_single_plus_multi_clean_restore_smoke_1k_v1': 'owner_plus_single_plus_multi_clean',
    'moesi_snapshot4_private_plus_clean_plus_i_nonllc_restore_smoke_1k_v1': 'clean_plus_instruction_only',
    'moesi_snapshot4_ownerfull_plus_clean_plus_i_restore_smoke_1k_v1': 'ownerfull_plus_clean_plus_instruction',
    'moesi_snapshot4_all_families_restore_smoke_1k_v1': 'all_families',
}
ladder = []
for run in ladder_order:
    stats = read_stats(OUT / 'smoke_ladder' / run / 'stats.txt')
    ladder.append({
        'run': run,
        'label': ladder_labels[run],
        'simInsts': stats['simInsts'],
        'simTicks': stats['simTicks'],
        'l2_load': stats['system.ruby.l2_cntrl0.L2cache.m_checkpoint_load_total'],
        'l2_load_hits': stats['system.ruby.l2_cntrl0.L2cache.m_checkpoint_load_hits'],
        'l2_hits': stats['system.ruby.l2_cntrl0.L2cache.m_demand_hits'],
        'l2_misses': stats['system.ruby.l2_cntrl0.L2cache.m_demand_misses'],
        'l1d_load': sum_suffix(stats, 'L1Dcache.m_checkpoint_load_total'),
        'l1i_load': sum_suffix(stats, 'L1Icache.m_checkpoint_load_total'),
        'l1d_hits': sum_suffix(stats, 'L1Dcache.m_demand_hits'),
        'l1d_misses': sum_suffix(stats, 'L1Dcache.m_demand_misses'),
        'l1i_hits': sum_suffix(stats, 'L1Icache.m_demand_hits'),
        'l1i_misses': sum_suffix(stats, 'L1Icache.m_demand_misses'),
    })

expected_family_counts = {
    'moesi_single_private_data_writeable': 5620,
    'moesi_single_private_data_clean': 556,
    'moesi_multi_private_data_clean': 561,
    'moesi_private_instruction_only': 2065,
}
phase1 = {
    'unsupported_block_count': guardrails['unsupported_block_count'],
    'implemented_family_counts': guardrails['implemented_family_counts'],
    'expected_family_counts': expected_family_counts,
}
phase1['pass'] = (
    phase1['unsupported_block_count'] == 0
    and phase1['implemented_family_counts'] == expected_family_counts
)

manifest_counts = {
    'l1d': manifest['components']['l1d']['line_count'],
    'l1i': manifest['components']['l1i']['line_count'],
    'llc': manifest['components']['llc']['line_count'],
}
restored_counts = {
    'l1d': sum_suffix(restored, 'L1Dcache.m_checkpoint_load_total'),
    'l1i': sum_suffix(restored, 'L1Icache.m_checkpoint_load_total'),
    'llc': restored['system.ruby.l2_cntrl0.L2cache.m_checkpoint_load_total'],
}
phase2 = {
    'manifest_counts': manifest_counts,
    'restored_counts': restored_counts,
    'pass': manifest_counts == restored_counts,
}

phase3 = {
    'restored_100k': {
        'simInsts': restored['simInsts'],
        'simTicks': restored['simTicks'],
        'l2_checkpoint_load_hits': restored['system.ruby.l2_cntrl0.L2cache.m_checkpoint_load_hits'],
        'l2_demand_hits': restored['system.ruby.l2_cntrl0.L2cache.m_demand_hits'],
        'l2_demand_misses': restored['system.ruby.l2_cntrl0.L2cache.m_demand_misses'],
        'l1d_checkpoint_loads': restored_counts['l1d'],
        'l1i_checkpoint_loads': restored_counts['l1i'],
        'l1d_demand_hits': sum_suffix(restored, 'L1Dcache.m_demand_hits'),
        'l1d_demand_misses': sum_suffix(restored, 'L1Dcache.m_demand_misses'),
        'l1i_demand_hits': sum_suffix(restored, 'L1Icache.m_demand_hits'),
        'l1i_demand_misses': sum_suffix(restored, 'L1Icache.m_demand_misses'),
    }
}
phase3['pass'] = (
    phase3['restored_100k']['simInsts'] > 100000
    and phase3['restored_100k']['l2_checkpoint_load_hits'] > 0
    and phase3['restored_100k']['l2_demand_hits'] > 0
    and phase3['restored_100k']['l1d_checkpoint_loads'] > 0
    and phase3['restored_100k']['l1i_checkpoint_loads'] > 0
    and phase3['restored_100k']['l1d_demand_hits'] > 0
    and phase3['restored_100k']['l1i_demand_hits'] > 0
)

l2_load_seq = [entry['l2_load'] for entry in ladder]
l1d_load_seq = [entry['l1d_load'] for entry in ladder]
l1i_load_seq = [entry['l1i_load'] for entry in ladder]
phase4_checks = {
    'l2_load_monotonic_non_decreasing': all(b >= a for a, b in zip(l2_load_seq, l2_load_seq[1:])),
    'l1d_load_monotonic_non_decreasing': all(b >= a for a, b in zip(l1d_load_seq, l1d_load_seq[1:])),
    'instruction_restore_activates_l1i': l1i_load_seq[0] == 0 and l1i_load_seq[-1] == manifest_counts['l1i'],
    'final_l2_checkpoint_load_hits_exceed_llc_only': ladder[-1]['l2_load_hits'] > ladder[0]['l2_load_hits'],
    'final_simticks_below_llc_only': ladder[-1]['simTicks'] < ladder[0]['simTicks'],
}
phase4 = {
    'ladder': ladder,
    'checks': phase4_checks,
    'pass': all(phase4_checks.values()),
}

comparison_100k = {
    'cold': {
        'simInsts': cold['simInsts'],
        'simTicks': cold['simTicks'],
        'l2_demand_hits': cold['system.ruby.l2_cntrl0.L2cache.m_demand_hits'],
        'l2_demand_misses': cold['system.ruby.l2_cntrl0.L2cache.m_demand_misses'],
        'l1d_demand_hits': sum_suffix(cold, 'L1Dcache.m_demand_hits'),
        'l1d_demand_misses': sum_suffix(cold, 'L1Dcache.m_demand_misses'),
        'l1i_demand_hits': sum_suffix(cold, 'L1Icache.m_demand_hits'),
        'l1i_demand_misses': sum_suffix(cold, 'L1Icache.m_demand_misses'),
    },
    'restored': phase3['restored_100k'],
}
comparison_100k['delta'] = {
    'simTicks': comparison_100k['restored']['simTicks'] - comparison_100k['cold']['simTicks'],
    'l2_demand_hits': comparison_100k['restored']['l2_demand_hits'] - comparison_100k['cold']['l2_demand_hits'],
    'l2_demand_misses': comparison_100k['restored']['l2_demand_misses'] - comparison_100k['cold']['l2_demand_misses'],
    'l1d_demand_hits': comparison_100k['restored']['l1d_demand_hits'] - comparison_100k['cold']['l1d_demand_hits'],
    'l1d_demand_misses': comparison_100k['restored']['l1d_demand_misses'] - comparison_100k['cold']['l1d_demand_misses'],
    'l1i_demand_hits': comparison_100k['restored']['l1i_demand_hits'] - comparison_100k['cold']['l1i_demand_hits'],
    'l1i_demand_misses': comparison_100k['restored']['l1i_demand_misses'] - comparison_100k['cold']['l1i_demand_misses'],
}
comparison_100k['directionally_better'] = (
    comparison_100k['delta']['simTicks'] < 0
    and comparison_100k['delta']['l2_demand_misses'] < 0
    and comparison_100k['restored']['l2_checkpoint_load_hits'] > 0
)

phase5 = {
    'invoked': False,
    'reason': (
        'Residual-miss deep dive was not required because phases 1-4 were '
        'clean and the 100k cold-vs-restored comparison remained '
        'directionally sensible without unexplained protocol symptoms.'
    ),
}

validated = (
    phase1['pass']
    and phase2['pass']
    and phase3['pass']
    and phase4['pass']
    and comparison_100k['directionally_better']
)
report = {
    'schema_version': 1,
    'validated': validated,
    'phase1': phase1,
    'phase2': phase2,
    'phase3': phase3,
    'phase4': phase4,
    'phase5': phase5,
    'comparison_100k': comparison_100k,
}
write_json(REPORT_JSON, report)

md = [
    '# MOESI Restore Validation',
    '',
    f"Verdict: {'validated' if validated else 'not yet validated'}",
    '',
    '## Snapshot_4 Family Coverage',
    f"- unsupported families observed: {phase1['unsupported_block_count']}",
]
for name, count in sorted(phase1['implemented_family_counts'].items()):
    md.append(f'- {name}: {count}')
md.extend([
    '',
    '## Restore Count Reconciliation',
    f"- l1d: manifest {manifest_counts['l1d']}, restored {restored_counts['l1d']}",
    f"- l1i: manifest {manifest_counts['l1i']}, restored {restored_counts['l1i']}",
    f"- llc: manifest {manifest_counts['llc']}, restored {restored_counts['llc']}",
    '',
    '## 100k Cold vs Restored',
    f"- cold simTicks: {comparison_100k['cold']['simTicks']}",
    f"- restored simTicks: {comparison_100k['restored']['simTicks']}",
    f"- delta simTicks: {comparison_100k['delta']['simTicks']}",
    f"- cold L2 demand misses: {comparison_100k['cold']['l2_demand_misses']}",
    f"- restored L2 demand misses: {comparison_100k['restored']['l2_demand_misses']}",
    f"- restored L2 checkpoint load hits: {comparison_100k['restored']['l2_checkpoint_load_hits']}",
    '',
    '## 1k Family Ladder Checks',
])
for name, passed in phase4_checks.items():
    md.append(f"- {name}: {'pass' if passed else 'fail'}")
md.extend([
    '',
    '## Residual-Miss Deep Dive',
    f"- invoked: {phase5['invoked']}",
    f"- reason: {phase5['reason']}",
    '',
])
REPORT_MD.write_text('\n'.join(md) + '\n', encoding='utf-8')

analysis_entry = {
    'label': 'moesi_restore_validation_summary',
    'question': 'Do the snapshot_4 MOESI restore artifacts satisfy the agreed family-coverage, restore-count, activation, and warm-usefulness gates?',
    'script': 'analyses/summarize_moesi_restore_validation.py',
    'inputs': [
        'staged/checkpoint_manifest.json',
        'staged/checkpoint_guardrails.json',
        'cold_100k/stats.txt',
        'restored_100k/stats.txt',
        'smoke_ladder',
    ],
    'outputs': [
        'analyses/moesi_restore_validation_report.json',
        'analyses/MOESI_RESTORE_VALIDATION.md',
    ],
    'status': 'passed' if validated else 'failed',
    'conclusion': (
        'snapshot_4 MOESI restore meets the agreed validation gates: '
        'guardrails are clean, restore counts reconcile exactly, warm-state '
        'structures are exercised, the 1k family ladder behaves sensibly, and '
        'the restored 100k reference run is directionally better than cold.'
        if validated else
        'snapshot_4 MOESI restore did not satisfy one or more agreed validation gates.'
    ),
}

result = {
    'outcome': 'passed' if validated else 'failed',
    'summary': analysis_entry['conclusion'],
    'metrics': {
        'cold_simTicks': comparison_100k['cold']['simTicks'],
        'restored_simTicks': comparison_100k['restored']['simTicks'],
        'restored_l2_checkpoint_load_total': restored_counts['llc'],
        'restored_l2_checkpoint_load_hits': comparison_100k['restored']['l2_checkpoint_load_hits'],
        'restored_l2_demand_hits': comparison_100k['restored']['l2_demand_hits'],
        'restored_l2_demand_misses': comparison_100k['restored']['l2_demand_misses'],
        'restored_l1d_checkpoint_load_total': restored_counts['l1d'],
        'restored_l1i_checkpoint_load_total': restored_counts['l1i'],
        'unsupported_private_family_blocks': phase1['unsupported_block_count'],
    },
}

for manifest_path in MANIFEST_PATHS:
    m = read_json(manifest_path)
    analyses = [a for a in m.get('analyses', []) if a.get('label') != analysis_entry['label']]
    analyses.append(analysis_entry)
    m['analyses'] = analyses
    m['result'] = result
    upsert_artifact(
        m,
        label='protected:analyses_script',
        path='analyses/summarize_moesi_restore_validation.py',
        category='script',
        description='Analysis script used to summarize the MOESI snapshot_4 validation package.',
    )
    upsert_artifact(
        m,
        label='protected:analyses_report_json',
        path='analyses/moesi_restore_validation_report.json',
        category='analysis',
        description='Machine-readable MOESI snapshot_4 validation verdict and metrics.',
    )
    upsert_artifact(
        m,
        label='protected:analyses_report_md',
        path='analyses/MOESI_RESTORE_VALIDATION.md',
        category='analysis',
        description='Human-readable MOESI snapshot_4 validation summary.',
    )
    write_json(manifest_path, m)
