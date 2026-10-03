"""Crop bundles: a portable copy of the training crops that loads bit-for-bit
like the source folders, so a cloud checkout trains the same model."""
from __future__ import annotations

import json

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')
pytest.importorskip('onnx')

from pipeline.cv_waqf import crop_bundle  # noqa: E402
from pipeline.cv_waqf.config import CROP_SIZE  # noqa: E402
from pipeline.cv_waqf.train_classifier import load_grouped_dataset  # noqa: E402


def _folders(tmp_path):
    rng = np.random.default_rng(3)
    roots = []
    for print_id in ('qatar', 'bahrain'):
        root = tmp_path / print_id
        for page in (1, 2, 3):
            for cls, name in (('s', 'ص'), ('j', 'ج'), ('none', 'none')):
                folder = root / cls
                folder.mkdir(parents=True, exist_ok=True)
                for k in range(2):
                    img = (rng.random((CROP_SIZE, CROP_SIZE)) * 255).astype(np.uint8)
                    cv2.imwrite(str(folder / f'p{page:03d}_w{k}_{name}.png'), img)
        roots.append(root)
    return roots


def test_bundle_loads_bit_identically_to_the_source_folders(tmp_path):
    roots = _folders(tmp_path)
    out = tmp_path / 'b.npz'
    crop_bundle.build(roots, out, validation_groups=['qatar:p0001'], note='t')
    x_dir, y_dir, g_dir = load_grouped_dataset(roots)
    x, y, groups, validation = crop_bundle.load(out)
    assert x.dtype == x_dir.dtype == np.float32
    assert np.array_equal(x, x_dir)            # exact, not approximately
    assert np.array_equal(y, y_dir)
    assert groups.tolist() == g_dir.tolist()
    assert validation == ['qatar:p0001']


def test_only_keeps_a_single_print_and_rejects_an_unknown_one(tmp_path):
    out = tmp_path / 'b.npz'
    crop_bundle.build(_folders(tmp_path), out, validation_groups=[])
    x, y, groups, _ = crop_bundle.load(out, only='qatar')
    assert len(y) == 18 and {g.split(':')[0] for g in groups.tolist()} == {'qatar'}
    with pytest.raises(ValueError, match="no crops from 'kuwait'"):
        crop_bundle.load(out, only='kuwait')


def test_summary_counts_by_print_and_class(tmp_path):
    out = tmp_path / 'b.npz'
    info = crop_bundle.build(_folders(tmp_path), out, validation_groups=['a:p0001'])
    assert info['crops'] == 36 and info['pages'] == 6
    assert info['by_source']['bahrain'] == {'ص': 6, 'ج': 6, 'none': 6}
    assert info['validation_groups'] == 1 and info['bytes'] > 0


def test_a_crop_without_a_page_group_is_refused(tmp_path):
    folder = tmp_path / 'qatar' / 's'
    folder.mkdir(parents=True)
    cv2.imwrite(str(folder / 'sample_x.png'), np.zeros((CROP_SIZE, CROP_SIZE), np.uint8))
    with pytest.raises(ValueError, match='page group'):
        crop_bundle.build([tmp_path / 'qatar'], tmp_path / 'b.npz', validation_groups=[])


def test_a_bundle_from_a_different_class_order_is_refused(tmp_path):
    out = tmp_path / 'b.npz'
    crop_bundle.build(_folders(tmp_path), out, validation_groups=[])
    with np.load(out, allow_pickle=False) as bundle:
        arrays = {k: bundle[k] for k in bundle.files}
    meta = json.loads(str(arrays['meta']))
    meta['classes'] = list(reversed(meta['classes']))
    arrays['meta'] = np.asarray(json.dumps(meta, ensure_ascii=False))
    bad = tmp_path / 'bad.npz'
    np.savez_compressed(bad, **arrays)
    with pytest.raises(ValueError, match='class order'):
        crop_bundle.load(bad)


def test_prepare_from_a_bundle_uses_its_validation_pages_and_only(tmp_path):
    from pipeline.cv_waqf.train_cnn_data import prepare

    out = tmp_path / 'b.npz'
    crop_bundle.build(
        _folders(tmp_path), out, validation_groups=['qatar:p0001', 'bahrain:p0002'],
    )
    # --only qatar: the bahrain validation group is absent, qatar's is used.
    info = prepare(None, tmp_path / 'q.npz', bundle=out, only='qatar', augment=1)
    assert info['crops'] == 18 and info['val'] == 6 and info['train'] == 12
    with np.load(tmp_path / 'q.npz') as data:
        assert set(data['val_idx'].tolist()).isdisjoint(data['train_idx'].tolist())
    with pytest.raises(ValueError, match='needs --bundle'):
        prepare([tmp_path], tmp_path / 'z.npz', only='qatar')


def test_the_checked_in_bundle_matches_the_documented_recipe():
    from pipeline.cv_waqf.config import ROOT

    path = ROOT / 'data' / 'cv' / 'bundles' / 'multiprint_crops_v1.npz'
    if not path.is_file():
        pytest.skip('bundle lives on the cloud-training branch')
    info = crop_bundle.summarize(path)
    assert set(info['by_source']) == {'bahrain', 'qatar'}
    assert info['crops'] == 23952 and info['pages'] == 259
    assert info['validation_groups'] == 31
