# AUTOGENERATED! DO NOT EDIT! File to edit: 05_heuristics.ipynb (unless otherwise specified).

__all__ = ['f_score', 'load_pred_model', 'multivariate_anomaly_score', 'get_score_df', 'get_preds', 'get_th_df',
           'get_best_threshhold', 'get_fixed_heuristic', 'get_ratio_th', 'elbow_heuristic',
           'get_lowest_plateau_heuristic', 'get_plot_data']

# Cell
from .imports import *
from .data_processing import *

from .anomaly import *
import seaborn as sns
sns.set_theme(style="darkgrid")

# Cell
from sklearn.metrics import confusion_matrix

def f_score(y_true, y_pred,sample_weight=None):
    C = confusion_matrix(y_true, y_pred, sample_weight=sample_weight)
    with np.errstate(divide="ignore", invalid="ignore"):
        per_class = np.diag(C) / C.sum(axis=1)
    if np.any(np.isnan(per_class)):
        warnings.warn("y_pred contains classes not in y_true")
        per_class = per_class[~np.isnan(per_class)]
    P = per_class[0]
    N = per_class[1]
    score = 2*(P*N)/(P+N)
    return score

# Cell
def load_pred_model(learner_path,train_log_path,log_name,cols=['activity']):
    p = f'{learner_path}/{log_name}_vocab.p'
    with open(p, 'rb') as fp:
        categorify = pickle.load(fp)
    log = import_log(train_log_path)
    o = process_test(log,categorify,cols)
    dls=o.get_dls()
    loss=partial(multi_loss_sum,o)
    emb_szs = get_emb_sz(o)
    m=MultivariateModel(emb_szs)
    learn=Learner(dls, m, path=learner_path, model_dir='.', loss_func=loss, metrics=get_metrics(o))
    learn.load(log_name,with_opt=False)
    m=learn.model.cuda()
    return m, categorify

# Cell
def multivariate_anomaly_score(res,o,idx,cols,normalization = True):
    score_df=pd.DataFrame()

    for cidx,_ in enumerate(cols):
        sm = nn.Softmax(dim=1)
        p = sm(res[cidx].cpu())
        pred = p.max(1)[0]
        y = o.items[cols[cidx]].iloc[idx].values

        truth=p[list(range(len(y))),y]
        if normalization:
            score = ((pred - truth) / pred).tolist()
        else:
            score = (pred - truth).tolist()
        score_df[cols[cidx]] = score
    score_df['trace_id']=o.items['trace_id'].iloc[idx].values
    return score_df

# Cell
def get_score_df(log_name,pdc_year=2020,prediction_normalization = True):
    learner_path=f'models/pdc{pdc_year}'
    training_log_path = f'data/csv/PDC{pdc_year}_training/pdc_{pdc_year}_{log_name}.csv.gz'
    test_log_path = f'data/csv/PDC{pdc_year}_ground_truth/pdc_{pdc_year}_{log_name}.csv.gz'

    cols = ['activity']
    m, categorify= load_pred_model(learner_path,training_log_path,log_name)
    if type(test_log_path)==str:
        log = import_log(test_log_path)
    else:
        log = test_log_path
    o = process_test(log,categorify,cols)
    nsp,idx=predict_next_step(o,m)
    score_df=multivariate_anomaly_score(nsp,o,idx,cols,prediction_normalization)
    y_true =o.items.groupby(o.items.index)['normal'].mean().to_numpy() == False
    return score_df,y_true

# Cell
def get_preds(score_df,threshold):
    h =score_df.groupby('trace_id')['activity'].max()
    h=(h-h.min())/(h.max()-h.min())

    y_pred = (h.to_numpy()>threshold).astype(int)
    return y_pred


# Cell
def get_th_df(ths,score_df,y_true,log_name,f_score=f_score):
    res = []
    for t in progress_bar(ths):
        y_pred=get_preds(score_df,t)
        anomaly_ratio = sum(x == 1 for x in y_pred) / len(y_pred)
        f1 = f_score(y_true, y_pred)
        precision = precision_score(y_true,y_pred)
        recall = recall_score(y_true,y_pred)
        res.append([log_name, f1, precision, recall, anomaly_ratio])

    columns='Log Name', 'F1 Score','Precision','Recall', 'Anomaly Ratio'
    th_df = pd.DataFrame(res,columns=columns,index=ths)
    return th_df


# Cell
def get_best_threshhold(th_df): return th_df.iloc[th_df['F1 Score'].argmax()]


# Cell
def get_fixed_heuristic(fixed,th_df): return th_df.iloc[np.absolute(th_df.index.to_numpy()-fixed).argmin()]


# Cell
def get_ratio_th(ratio,th_df):return th_df.iloc[th_df['Anomaly Ratio'].sub(ratio).abs().argmin()]


# Cell
def elbow_heuristic(th_df):
    taus = th_df.index.to_numpy()
    r = th_df['Anomaly Ratio'].to_numpy()
    step = taus[1:] - taus[:-1]
    r_prime_prime = (r[2:] - 2 * r[1:-1] + r[:-2]) / (step[1:] * step[:-1])
    ellbow_down = th_df.iloc[np.argmax(r_prime_prime) + 1]
    ellbow_up = th_df.iloc[np.argmin(r_prime_prime) + 1]
    return ellbow_down,ellbow_up


# Cell
def get_lowest_plateau_heuristic(th_df):
    taus = th_df.index.to_numpy()
    r = th_df['Anomaly Ratio'].to_numpy()
    r_prime = (r[1:] - r[:-1]) / (taus[1:] - taus[:-1])
    stable_region = r_prime > np.mean(r_prime) / 2
    regions = np.split(np.arange(len(stable_region)), np.where(~stable_region)[0])
    regions = [taus[idx[1:]] for idx in regions if len(idx) > 1]
    if len(regions) == 0:
        regions = [taus[-2:]]
    lp_min = get_fixed_heuristic(regions[-1].min(),th_df)
    lp_mean = get_fixed_heuristic(regions[-1].mean(),th_df)
    lp_max = get_fixed_heuristic(regions[-1].max(),th_df)
    return lp_min,lp_mean,lp_max


# Cell
def get_plot_data(th_df,id_vars=['Log Name'],value_vars = ['F1 Score','Anomaly Ratio']):
    plot_data=th_df.melt(var_name='Metric',value_name='Score',id_vars =id_vars ,value_vars=value_vars,ignore_index=False)
    plot_data['Threshold']=plot_data.index
    plot_data.index=range(len(plot_data))
    return plot_data
