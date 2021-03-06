#!/Users/sunnymarkliu/softwares/miniconda3/bin/python
# _*_ coding: utf-8 _*_

"""
@author: SunnyMarkLiu
@time  : 2018/6/27 下午8:27
"""
import os
import sys

sys.path.append("../")
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import log_loss
from sklearn.model_selection import StratifiedKFold
from utils import data_loader
from conf.configure import Configure


def get_xgb_importance(clf, features):
    weughts_imp = clf.get_score(importance_type='weight')
    gains_imp = clf.get_score(importance_type='gain')
    covers_imp = clf.get_score(importance_type='cover')

    weights = []
    gains = []
    covers = []
    for f in features:
        weights.append(weughts_imp.get(f, 0))
        gains.append(gains_imp.get(f, 0))
        covers.append(covers_imp.get(f, 0))

    features_imp = pd.DataFrame({'feature': features, 'weights': weights, 'gains': gains, 'covers': covers})
    sum_weight = sum(features_imp['weights']) * 1.0
    features_imp['weights'] = features_imp['weights'] / sum_weight
    features_imp['importance'] = features_imp['weights'] + features_imp['gains'] + features_imp['covers']
    del features_imp['weights']
    del features_imp['gains']
    del features_imp['covers']

    impdf = features_imp.sort_values(by='importance', ascending=False).reset_index(drop=True)
    impdf['importance'] /= impdf['importance'].sum()
    return impdf


def load_dataset():
    """ 加载 level1 的 roof 的预测结果 """
    train_df = pd.read_csv('../input/train.csv')

    base = Configure.save_ensemble_dir
    roof_result = os.listdir(base)
    train = pd.DataFrame({'label': train_df['label']})
    test = pd.DataFrame()
    roof_count = 0
    for f in roof_result:
        feature = '_'.join(f[:-4].split('_')[1:])
        if f.startswith('test'):
            test_i = pd.read_csv(base + f)
            test[feature] = test_i['y_pre']
            roof_count += 1
        else:
            train_i = pd.read_csv(base + f)
            train[feature] = train_i['y_pre']

    train = train[['label'] + test.columns.values.tolist()]

    print('loaded {} model features'.format(roof_count))

    train_features, test_features = data_loader.load_features()

    train[train_features.columns] = train_features
    test[train_features.columns] = test_features
    # 加载伪标签数据
    test_df = pd.read_csv(Configure.pseudo_label_test)
    test['label'] = test_df['y_pre'].map(lambda x: int(x > 0.5))

    delete_features = ['cosine_distance', 'minkowski_distance', 'canberra_distance']
    delete_features = delete_features + ['char_cityblock_distance',
                                         'chars_tfidf_wm',
                                         'braycurtis_distance',
                                         'words_tfidf_wm',
                                         'char_match',
                                         'tfidf_sim',
                                         'jaccard_distance',
                                         'lda_11_x',
                                         'lda_14_x',
                                         'lda_13_x',
                                         'char_euclidean_distance',
                                         'char_cosine_distance',
                                         'word_match',
                                         '_jaccard',
                                         'graph_2',
                                         'lda_0_x',
                                         'lda_1_x',
                                         'lda_2_x',
                                         'lda_4_x',
                                         'lda_5_x',
                                         'lda_6_x',
                                         'lda_7_x',
                                         'lda_8_x',
                                         'lda_9_x',
                                         'lda_10_x',
                                         'char_jaccard_distance',
                                         'lda_12_x',
                                         'lda_3_x']

    train.drop(delete_features, axis=1, inplace=True)
    test.drop(delete_features, axis=1, inplace=True)

    return train, test


def main():
    print("load train test datasets")
    train, test = load_dataset()
    y_train_all = train['label'].values
    test_pre_lebels = test['label'].values

    train.drop(['label'], axis=1, inplace=True)
    test.drop(['label'], axis=1, inplace=True)
    df_columns = train.columns.values

    train = train.values
    test = test.values
    # train = np.concatenate((train.values, test.values), axis=0)
    # y_train_all = np.concatenate((y_train_all, test_pre_lebels), axis=0)

    print('train: {}, test: {}, feature count: {}, label 1:0 = {:.5f}'.format(
        train.shape, test.shape, len(df_columns), 1.0 * sum(y_train_all) / len(y_train_all)))

    xgb_params = {
        'eta': 0.005,
        'max_depth': 6,
        'subsample': 0.9,
        'eval_metric': 'logloss',
        'objective': 'binary:logistic',
        'updater': 'grow_gpu',
        'gpu_id': 2,
        'nthread': -1,
        'silent': 1,
        'booster': 'gbtree',
    }

    dtest = xgb.DMatrix(test, feature_names=df_columns)

    pred_train_full = np.zeros(train.shape[0])
    pred_test_full = 0
    cv_scores = []
    roof_flod = 5

    kf = StratifiedKFold(n_splits=roof_flod, shuffle=True, random_state=5201314)
    for i, (dev_index, val_index) in enumerate(kf.split(train, y_train_all)):
        print('========== perform fold {}, train size: {}, validate size: {} =========='.format(i, len(dev_index),
                                                                                                len(val_index)))
        train_x, val_x = train[dev_index], train[val_index]
        train_y, val_y = y_train_all[dev_index], y_train_all[val_index]
        dtrain = xgb.DMatrix(train_x, label=train_y, feature_names=df_columns)
        dval = xgb.DMatrix(val_x, label=val_y, feature_names=df_columns)

        model = xgb.train(xgb_params, dtrain,
                          evals=[(dtrain, 'train'), (dval, 'valid')],
                          verbose_eval=100,
                          early_stopping_rounds=100,
                          num_boost_round=4000)

        fea_imp = get_xgb_importance(model, features=df_columns)
        fea_imp.to_csv("feature_importance.csv", index=False, columns=['feature', 'importance'], sep='\t')

        # predict validate
        predict_valid = model.predict(dval, ntree_limit=model.best_ntree_limit)
        valid_auc = log_loss(val_y, predict_valid, eps=1e-10)
        # predict test
        predict_test = model.predict(dtest, ntree_limit=model.best_ntree_limit)

        print('valid_logloss = {}'.format(valid_auc))
        cv_scores.append(valid_auc)

        # run-out-of-fold predict
        pred_train_full[val_index] = predict_valid
        pred_test_full += predict_test

    mean_cv_scores = np.mean(cv_scores)
    print('Mean cv logloss:', mean_cv_scores)

    print("saving test predictions for ensemble")
    pred_test_full = pred_test_full / float(roof_flod)
    test_pred_df = pd.DataFrame({'y_pre': pred_test_full})
    test_pred_df.to_csv("final_xgboost_stacking_models.csv", index=False, columns=['y_pre'], sep='\t')

    print('-------- predict and check  ------')
    print('test 1 count: {:.6f}, mean: {:.6f}'.format(np.sum(test_pred_df['y_pre']), np.mean(test_pred_df['y_pre'])))
    print('done.')


if __name__ == '__main__':
    print('========== xgboost stacking ==========')
    main()
