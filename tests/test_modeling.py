import numpy as np
import pytest

from acustica_materiales.modeling import object_weights, object_folds, aggregate_probabilities


def test_all_impacts_of_object_remain_together_and_all_classes_train():
    y=np.array(['hierro']*5+['madera']*7)
    groups=np.array(['h1']*2+['h2']*3+['m1']*3+['m2']*4)
    seen=[]
    for train,test in object_folds(y,groups):
        assert set(groups[train]).isdisjoint(groups[test])
        assert len(set(groups[test]))==1
        assert set(y[train])==set(y)
        seen.extend(test)
    assert sorted(seen)==list(range(len(y)))


def test_refuse_single_object_class_and_inconsistent_labels():
    with pytest.raises(ValueError):
        object_folds(['a','a','b'],['a1','a2','b1'])
    with pytest.raises(ValueError):
        object_folds(['a','b','a','b'],['obj1','obj1','obj2','obj3'])


def test_weights_equalize_classes_and_objects_despite_unequal_repetitions():
    y=np.array(['a']*2+['b']*7)
    groups=np.array(['a1']*2+['b1']*3+['b2']*4)
    weights=object_weights(y,groups)
    assert weights.sum()==pytest.approx(len(y))
    assert weights[y=='a'].sum()==pytest.approx(weights[y=='b'].sum())
    assert weights[groups=='b1'].sum()==pytest.approx(weights[groups=='b2'].sum())


def test_probability_aggregation_is_per_object_not_per_material():
    p=np.array([[.9,.1],[.1,.9],[.3,.7]])
    result=aggregate_probabilities(['x','y','x'],p)
    assert np.allclose(result['x'],[.6,.4])
    assert np.allclose(result['y'],[.1,.9])
