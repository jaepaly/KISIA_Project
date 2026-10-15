"""벤치마크 조립·등급 지표·안전장치 — 모델과 실제 test 없이 확인한다."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bench_c1_run', Path(__file__).with_name('run.py'))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def fixture():
    span = {'span_id': 'x_s01', 'text_id': 'body', 'start': 0, 'end': 4,
            'text': 'abcd', 'type': 'AGE', 'level': 'explicit', 'subject': 'self'}
    posts = {'x': {'post_id': 'x', 'texts': {'body': 'abcdefghij'}}}
    gold = {'x': {**posts['x'], 'reviewed': True, 'spans': [span]}}
    predictions = {'x': [{**span, 'score': .9}]}
    return posts, gold, predictions


class MetricsTests(unittest.TestCase):
    def test_proxy_is_not_level_prediction(self):
        posts, gold, predictions = fixture()
        predictions['x'][0]['level'] = 'implicit'
        result = bench.score_predictions(posts, gold, predictions)
        self.assertEqual(result['proxy']['partial_by_level']['explicit']['proxy_f1'], 1)
        self.assertEqual(result['resolved_level']['partial']['overall']['tp'], 0)
        self.assertEqual(result['resolved_level']['partial']['by_level']['implicit']['fp'], 1)
        self.assertEqual(result['resolved_level']['partial']['by_level']['explicit']['fn'], 1)

    def test_partial_and_exact_are_separate(self):
        posts, gold, predictions = fixture()
        predictions['x'][0].update(end=5, text='abcde')
        result = bench.score_predictions(posts, gold, predictions)
        self.assertEqual(result['boundary_type']['partial']['overall']['tp'], 1)
        self.assertEqual(result['boundary_type']['exact']['overall']['tp'], 0)
        self.assertEqual(result['proxy']['exact_by_level']['explicit']['proxy_f1'], 0)

    def test_no_gold_level_is_null(self):
        result = bench.score_predictions(*fixture())
        self.assertIsNone(result['proxy']['partial_by_level']['implicit']['proxy_f1'])
        self.assertIsNone(result['resolved_level']['partial']['by_level']['implicit']['f1'])
        self.assertIsNone(result['implicit_iaa']['proxy_percent'])

    def test_no_predictions_is_not_missing_record(self):
        posts, gold, _ = fixture()
        result = bench.score_predictions(posts, gold, {'x': []})
        self.assertEqual(result['boundary_type']['partial']['overall']['fn'], 1)
        with self.assertRaises(bench.DataError):
            bench.score_predictions(posts, gold, {})

    def test_subject_is_not_match_condition(self):
        posts, gold, predictions = fixture()
        predictions['x'][0]['subject'] = 'other'
        self.assertEqual(bench.score_predictions(posts, gold, predictions)
                         ['resolved_level']['partial']['overall']['tp'], 1)

    def test_duplicate_or_invalid_prediction_rejected(self):
        posts, gold, predictions = fixture()
        for spans in ([predictions['x'][0]] * 2, [{**predictions['x'][0], 'text': 'bad'}]):
            with self.assertRaises((bench.infer.InferenceError, Exception)):
                bench.score_predictions(posts, gold, {'x': spans})

    def test_gold_reviewed_and_source_guards(self):
        posts, gold, _ = fixture()
        bench.validate_gold(posts, gold)
        for change in ({'reviewed': False}, {'texts': {'body': 'different'}}):
            with self.assertRaises(bench.DataError):
                bench.validate_gold(posts, {'x': {**gold['x'], **change}})

    def test_additional_allows_rules_and_v2(self):
        posts, gold, predictions = fixture()
        result = bench.additional.score_additional_rate(gold, predictions, {('x', 'body'): []}, 1)
        self.assertEqual(result['overall']['additional_rate'], 1)
        result = bench.additional.score_additional_rate(gold, predictions,
                    {('x', 'body'): [{'start': 0, 'end': 4, 'type': 'PERSON'}]}, 1)
        self.assertIsNone(result['overall']['additional_rate'])

    def test_additional_missing_channel_or_wrong_tp_rejected(self):
        _, gold, predictions = fixture()
        for tools, tp in [({}, 1), ({('x', 'body'): []}, 0)]:
            with self.assertRaises(bench.DataError):
                bench.additional.score_additional_rate(gold, predictions, tools, tp)

    def test_baseline_fallback_rejected(self):
        presidio = types.ModuleType('run_presidio')
        presidio.HAS_PRESIDIO = True
        presidio.build_analyzer = lambda: types.SimpleNamespace(supported_languages=['ko', 'en'])
        ner = types.ModuleType('run_koreanpii')
        ner._NLP = object()
        with patch.dict('sys.modules', {'run_regex': types.ModuleType('run_regex'),
                                       'run_presidio': presidio, 'run_koreanpii': ner}):
            with self.assertRaises(bench.DataError):
                bench.additional.run_baselines({})

    def test_iaa_percent_is_reference_ratio(self):
        posts, gold, predictions = fixture()
        gold['x']['spans'][0]['level'] = 'implicit'
        predictions['x'][0]['level'] = 'implicit'
        self.assertAlmostEqual(bench.score_predictions(posts, gold, predictions)
                               ['implicit_iaa']['proxy_percent'], 100 / .444)


class SafetyTests(unittest.TestCase):
    def args(self, *extra):
        return ['--checkpoint-dir', 'unused-model', '--output-dir',
                str(bench.ROOT / 'experiments/bench/runs/unittest-never-written'), *extra]

    def test_test_requires_confirmation(self):
        with self.assertRaises(SystemExit):
            bench.parse_args(self.args('--split', 'test'))

    def test_final_cannot_use_smoke_options(self):
        for extra in [('--limit', '2'), ('--skip-baselines',), ('--skip-latency',), ('--repeats', '1')]:
            with self.assertRaises(SystemExit):
                bench.parse_args(self.args('--split', 'test', '--final-test-confirm', *extra))

    def test_defaults_are_train_and_manual_cpu_protocol(self):
        args = bench.parse_args(self.args())
        self.assertEqual((args.split, args.rules, args.threads, args.warmup, args.repeats),
                         ('train', 'on', 4, 5, 50))

    def test_outside_runs_and_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for target in (tmp, str(bench.ROOT / 'output-not-runs')):
                with self.assertRaises(SystemExit):
                    bench.parse_args(['--checkpoint-dir', 'unused', '--output-dir', target])

    def test_train_loader_does_not_open_test_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'splits').mkdir()
            (root / 'gold').mkdir()
            forbidden = [f'test_{i}' for i in range(255)]
            (root / 'splits/test_post_ids.json').write_text(json.dumps({'post_ids': forbidden}), encoding='utf-8')
            posts, gold, _ = fixture()
            p2, g2 = copy.deepcopy(posts['x']), copy.deepcopy(gold['x'])
            p2['post_id'] = g2['post_id'] = 'y'
            (root / 'splits/train.jsonl').write_text('\n'.join(map(json.dumps, [posts['x'], p2])), encoding='utf-8')
            (root / 'gold/X_spans.jsonl').write_text('\n'.join(map(json.dumps, [gold['x'], g2])), encoding='utf-8')
            args = bench.parse_args(self.args('--corpus-dir', str(root), '--limit', '2'))
            selected, _, audit = bench.load_dataset(args)
            self.assertEqual(set(selected), {'x', 'y'})
            self.assertFalse(audit['test_body_opened'])
            self.assertFalse((root / 'splits/test.jsonl').exists())

    def test_checkpoint_training_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp)
            self.assertIsNone(bench.checkpoint_data_sha256(ckpt))   # v1: 지문 없음
            (ckpt / 'trainer_state.json').write_text(json.dumps(
                {'eval': {'run_config': {'data_sha256': 'ab' * 32}}}), encoding='utf-8')
            self.assertEqual(bench.checkpoint_data_sha256(ckpt), 'ab' * 32)

    def test_test_rejects_bio_other_than_trained(self):
        args = types.SimpleNamespace(split='test', final_test_confirm=True, limit=None,
                                     corpus_dir=Path('c'), bio_data=Path('bio.jsonl'), checkpoint_dir=Path('k'))
        audit = {'limitations': ['Current BIO checked for leakage; x']}
        with patch.object(Path, 'exists', return_value=True), patch.object(bench.train, 'file_sha256', side_effect=lambda p: 'other' if p == Path('bio.jsonl') else bench.TEST_SHA256),                 patch.object(bench, 'test_ids', return_value={'x'}),                 patch.object(bench.evaluation, 'records', return_value=[]),                 patch.object(bench.evaluation, 'index_posts', return_value={'x': {}}),                 patch.object(bench.evaluation, 'prepare', return_value=({str(i): {} for i in range(239)}, {}, audit)):
            with patch.object(bench, 'checkpoint_data_sha256', return_value='trained'):
                with self.assertRaises(bench.DataError):
                    bench.load_dataset(args)
            with patch.object(bench, 'checkpoint_data_sha256', return_value=None):
                _, _, out = bench.load_dataset(args)
                self.assertFalse(out['training_data_sha256']['verified'])
                self.assertTrue(any(x.startswith('Current BIO checked') for x in out['limitations']))

    def test_latency_uses_same_sample_and_measure_helper(self):
        posts = {str(i): {'post_id': str(i), 'texts': {'body': 'a' * (i + 1)}} for i in range(5)}
        calls = []
        def measured(detector, post, warmup, repeats):
            calls.append((post['post_id'], warmup, repeats))
            return [10., 20., 30.]
        with patch.object(bench.latency, 'measure_one', side_effect=measured):
            result = bench.measure_latency(posts, lambda p: None, lambda p: None, 2, 5, 3)
        self.assertEqual(calls[:2], calls[2:])
        self.assertEqual(result['model_only']['distribution_ms']['median'], 20.)
        self.assertEqual(result['app_full']['distribution_ms']['under_300_posts'], 2)

    def test_full_runner_without_real_model_or_baselines(self):
        posts, gold, _ = fixture()
        posts['y'] = {'post_id': 'y', 'texts': {'body': 'abcdefghij'}}
        gold['y'] = copy.deepcopy(gold['x'])
        gold['y']['post_id'] = 'y'
        gold['y']['spans'][0]['span_id'] = 'y_s01'
        class FakeDetector:
            version, batch_size, max_length, stride = 'fake', 16, 256, 64
            def __init__(self, *args, **kwargs):
                pass
            def predict_raw(self, record):
                pid = record['post_id']
                candidate = {'span_id': pid + '_s01', 'text_id': 'body', 'start': 0, 'end': 4,
                             'text': 'abcd', 'type': 'AGE', 'score': .9}
                return {'post_id': pid, 'record_type': 'post', 'texts': record['texts'],
                        'candidates': [candidate], 'model_version': self.version}
            def detect(self, record, resolver=None):
                return bench.infer.format_contract(self.predict_raw(record), resolver or bench.infer.legacy_attributes)
        torch = types.ModuleType('torch')
        torch.__version__ = 'test-only'
        torch.set_num_threads = lambda n: None
        torch.get_num_threads = lambda: 4
        transformers = types.ModuleType('transformers')
        transformers.__version__ = 'test-only'
        with tempfile.TemporaryDirectory() as tmp:
            args = bench.parse_args(self.args('--warmup', '0', '--repeats', '1', '--latency-samples', '2'))
            args.output_dir = Path(tmp) / 'out'
            tools = {(pid, 'body'): [] for pid in posts}
            with patch.object(bench, 'parse_args', return_value=args), \
                 patch.object(bench, 'load_dataset', return_value=(posts, gold, {'test_body_opened': False})), \
                 patch.object(bench.infer, 'SpanDetector', FakeDetector), \
                 patch.object(bench.additional, 'run_baselines', return_value=(tools, {'test_fixture': True})), \
                 patch('c1_rules._ENABLED', True), \
                 patch.dict('sys.modules', {'torch': torch, 'transformers': transformers}), \
                 patch('sys.stdout', new_callable=io.StringIO):
                bench.main([])
            report = json.loads((args.output_dir / 'metrics.json').read_text(encoding='utf-8'))
            self.assertEqual(report['c1']['boundary_type']['partial']['overall']['tp'], 2)
            self.assertEqual(report['additional_detection']['overall']['recovered'], 2)
            self.assertEqual(report['cpu_latency']['status'], 'measured')
            self.assertEqual(report['scope'], 'development_smoke_not_final')
            self.assertEqual(len((args.output_dir / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()), 2)


if __name__ == '__main__':
    unittest.main()
