"""Verify saved predictions independently; no upstream analysis imports."""
from pathlib import Path
import json
import hashlib
import math
import sys
import tempfile
import unittest
import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from verify_source import verify_source

class SavedResultsTests(unittest.TestCase):
    def test_cohort_and_grouping(self):
        features=pd.read_csv(ROOT/'results/duration_features.csv')
        predictions=pd.read_csv(ROOT/'results/oof_predictions.csv')
        self.assertEqual(len(features),117)
        self.assertEqual(features.long_logged_event.sum(),34)
        self.assertEqual(features.logged_duration_min.sum(),6222)
        self.assertEqual(features.date.nunique(),80)
        self.assertTrue(predictions.groupby('date').fold.nunique().eq(1).all())
        self.assertEqual(features.incident_id.tolist(),predictions.incident_id.tolist())
        self.assertEqual(features.long_logged_event.tolist(),predictions.long_logged_event.tolist())

    def test_oof_metrics_and_baseline(self):
        table=pd.read_csv(ROOT/'results/oof_predictions.csv')
        result=json.loads((ROOT/'results/model_results.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'results/duration_features.csv').read_bytes()).hexdigest(),result['prepared_feature_sha256'])
        y=table.long_logged_event.to_numpy()
        for row in result['oof_metrics']:
            p=table['p_long_'+row['model']].to_numpy()
            self.assertTrue(np.isfinite(p).all() and ((p>=0)&(p<=1)).all())
            for key,value in [('roc_auc',roc_auc_score(y,p)),('average_precision',average_precision_score(y,p)),('brier_score',brier_score_loss(y,p))]:
                self.assertAlmostEqual(value,row[key],places=12)
        for fold in sorted(table.fold.unique()):
            train=table.fold.ne(fold)
            expected=table.loc[train,'long_logged_event'].mean()
            np.testing.assert_allclose(table.loc[~train,'p_long_dummy_prior'],expected,rtol=0,atol=1e-14)

    def test_event_probability_and_pudo_contrast(self):
        p3=1-(184/(184+30))**3.5
        p1=1-(184/(184+30))**1.5
        self.assertAlmostEqual(p3,.41059451399633684,places=12)
        self.assertAlmostEqual(p1,.20272880325426046,places=12)
        self.assertLess(p3,1-(184/214)**6.5)
        rr=(79/4220075)/(177/10330467)
        p=binomtest(79,256,4220075/(4220075+10330467)).pvalue
        self.assertAlmostEqual(rr,1.092580915452844,places=12)
        self.assertAlmostEqual(p,.5353666932462805,places=12)
        interval=binomtest(79,256).proportion_ci(confidence_level=.95,method='exact')
        transform=lambda prob:prob/(1-prob)*10330467/4220075
        self.assertAlmostEqual(transform(interval.low),.8272003179033786,places=7)
        self.assertAlmostEqual(transform(interval.high),1.432220075105348,places=7)

    def test_changed_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            (root/'data').mkdir()
            (root/'data/AV-Brick-Report.xlsx').write_bytes(b'not-the-frozen-input')
            with self.assertRaisesRegex(ValueError,'Source hash mismatch'):
                verify_source(root)

if __name__=='__main__':unittest.main()
