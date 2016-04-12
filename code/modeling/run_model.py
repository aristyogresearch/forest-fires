import sys
import pickle
import pandas as pd
import numpy as np
import keras
import time
from scoring import return_scores
from datetime import timedelta, datetime
from time_val import SequentialTimeFold, StratifiedTimeFold
from sklearn.grid_search import GridSearchCV
from preprocessing import normalize_df, prep_data, alter_nearby_fires_cols 
from supervised_models import get_model 
from grid_search import sklearn_grid_search, get_grid_params 

def get_train_test(df, date_col, test_date): 
    """Return a train/test split based off the inputted test_date

    For the inputted DataFrame, break it into a train/test split, 
    where the train is all those rows prior to the test_date, and 
    the test is all the rows that fall on that day. 

    Args: 
    ----
        df: Pandas DataFrame
        date_col: str
            Holds the name of the date column in the `df` that 
            the train/test split will be made on. 
        test_date: datime.datime

    Return: 
    ------
        train: Pandas DataFrame
        test: Pandas DataFrame
    """

    # In the case that we are putting in a test_date for training, we 
    # want to make sure to only grab that day (and not days that are greater
    # than it, which will be present in training). 
    max_test_date = test_date + timedelta(days=1)

    # We're only going to go back 14 days to perform CV over. 
    min_train_date = test_date - timedelta(days=14)
    test_mask = np.where(np.logical_and(df[date_col] >= test_date, 
        df[date_col] < max_test_date))[0]
    train_mask = np.where(np.logical_and(df[date_col] < test_date, 
        df[date_col] >= min_train_date))
    train, test = df.ix[train_mask, :], df.ix[test_mask, :]

    return train, test

def get_model_args(model_name): 
    """Return the dictionary holding the kwargs passed to get_model."""
    pass

def predict_with_model(test_data, model): 
    '''
    Input: Pandas DataFrame, Fitted Model
    Output: Numpy Array of Predictions

    Using the fitted model, make predictions with the test data and return those predictions. 
    '''

    if isinstance(model, keras.models.Sequential): 
        target, features = get_target_features(test_data)
        predictions = model.predict(features.values)[:, 1] > 0.50 
        predicted_probs = model.predict_proba(features.values)
    else: 
        target, features = get_target_features(test_data)
        predictions = model.predict(features)
        predicted_probs = model.predict_proba(features)

    return predictions, predicted_probs

def log_results(model_name, train, fitted_model, scores, best_roc_auc, run_time): 
    '''
    Input: String, Pandas DataFrame,  Dictionary, Numpy Array, Float  
    Output: .txt file. 

    Log the results of this run to a .txt file, saving the column names (so I know what features I used), 
    the model name (so I know what model I ran), the parameters for that model, 
    and the scores associated with it (so I know how well it did). 
    '''

    st = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
    filename = 'code/modeling/model_output/logs/' + model_name + '.txt'
    with open(filename, 'a+') as f:
        f.write(st + '\n')
        f.write('-' * 100 + '\n')
        f.write('Model Run: ' + model_name + '\n' * 2)
        f.write('Params: ' + str(fitted_model.get_params()) + '\n' * 2)
        f.write('Features: ' + ', '.join(train.columns) + '\n' * 2)
        f.write('Scores: ' + str(scores) + '\n' * 2)
        f.write('Validation ROC AUC: ' + str(best_roc_auc) + '\n' * 2)
        f.write('Run time: ' + str(run_time) + '\n' * 2)

if __name__ == '__main__': 
    # sys.argv[1] will hold the name of the model we want to run (logit, 
    # random forest, etc.), and sys.argv[2] will hold our input dataframe 
    # (data will all the features and target). 
    model_name = sys.argv[1]

    base_input_df = pd.read_csv(sys.argv[2], parse_dates=['date_fire'])
    with open('code/makefiles/columns_list.pkl') as f: 
        keep_columns = pickle.load(f)

    input_df = base_input_df[keep_columns]
    input_df = alter_nearby_fires_cols(input_df)
    if len(sys.argv) == 4: 
        # If this is 4, I'm expecting that a date was passed in that we want
        # to use for the day of our test set (i.e. the days fires that we are 
        # predicting). Otherwise, we'll use the most recent date in our df. 
        date_parts = sys.argv[4].split('-')
        test_set_date = datetime(date_parts[0], date_parts[1], date_parts[2],
                0, 0, 0)
    else: 
        test_set_timestamp = input_df['date_fire'].max()
        test_set_date = datetime(test_set_timestamp.year, 
                test_set_timestamp.month, test_set_timestamp.day, 0, 0, 0)
    train, test = get_train_test(input_df, 'date_fire', test_set_date)

    # sklearn logit uses regularization by default, so it'd be best 
    # to scale the variables in that case as well. 
    if model_name == 'neural_net' or model_name == 'logit': 
        train = normalize_df(train)
        test = normalize_df(test)

        
    # We need to reset the index so the time folds produced work correctly.
    train.reset_index(drop=True, inplace=True)
    date_step_size = timedelta(days=1)
    cv_fold_generator = SequentialTimeFold(train, date_step_size, 20, 
            test_set_date)
    
    train, test = prep_data(train), prep_data(test)
    
    model_kwargs = get_model_args(model_name)
    model = get_model(model_name, model_kwargs)
    grid_parameters = get_grid_params(model_name)

    early_stopping_tolerance = 5 if model_name in {'xgboost' or 'gboosting'} \
            else None
    best_fit_model, mean_metric_score = \
            sklearn_grid_search(model, grid_parameters, train, 
            test, cv_fold_generator, early_stopping_tolerance, model_name) 

    preds, preds_probs = predict_with_model(test, best_fit_model)
    scores = return_scores(test.fire_bool, preds, preds_probs)
    log_results(model_name, train, best_fit_model, scores, mean_metric_score, 
            run_time)
