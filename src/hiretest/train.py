import pickle
import numpy as np
import pandas as pd
from sklearn.utils.class_weight import compute_class_weight
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from collections import Counter
from sklearn.metrics import precision_score, recall_score, f1_score,fbeta_score, classification_report, roc_auc_score
import os
import argparse
from pathlib import Path

try:
    from .paths import data_workspace_root
except ImportError:  # Support direct execution from src/hiretest.
    from paths import data_workspace_root


WORKSPACE_ROOT = data_workspace_root()
MODEL_DIR = WORKSPACE_ROOT / "models"
OUTPUT_DIR = WORKSPACE_ROOT / "outputs"


def _prepare_output(path):
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path

def load_by_student_split(pkl_path: str, train_ratio=0.3, random_state=42):
    """Split by student ID: randomly select train_ratio of students as the training set, the rest as the test set.
All samples belonging to a student go into the corresponding set.
"""
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
    
    df = pd.DataFrame(data)
    print(f"Total samples: {len(df)}, Students: {df['student_id'].nunique()}")
    print(f"Positive rate overall: {df['label'].mean():.1%}")

    #Get all unique student IDs
    all_students = df['student_id'].unique()
    np.random.seed(random_state)
    np.random.shuffle(all_students)

    n_train_students = int(len(all_students) * train_ratio)
    train_students = set(all_students[:n_train_students])
    test_students = set(all_students[n_train_students:])

    train_df = df[df['student_id'].isin(train_students)].reset_index(drop=True)
    test_df = df[df['student_id'].isin(test_students)].reset_index(drop=True)

    print(f"Train students: {len(train_students)}, samples: {len(train_df)} ({train_df['label'].mean():.1%} positive)")
    print(f"Test students: {len(test_students)}, samples: {len(test_df)} ({test_df['label'].mean():.1%} positive)")

    return train_df, test_df  

def encode_change_tree(change_data, type_vocab=None, token_vocab=None, max_nodes=50):
    """
Use path-context encoding.
Note: type_vocab and token_vocab parameters are no longer used, but retained for interface compatibility.
The actual used is path_context_vocab (passed through type_vocab, see below explanation)."""
    #To maintain compatibility with your calling method, we agree that:
    #type_vocab actually passes path_context_vocab
    path_context_vocab = type_vocab  #Rename for clarity


    if path_context_vocab is None:
        return np.array([])

    features = np.zeros(len(path_context_vocab), dtype=np.float32)

    def collect_and_encode(node, current_path):
        new_path = current_path + [node['node_type']]
        if node['content'].strip():
            tokens = node['content'].strip().split()
            for tok in tokens:
                key = (tuple(new_path), tok)
                if key in path_context_vocab:
                    idx = path_context_vocab[key]
                    if idx < len(features):
                        features[idx] += 1
        for child in node['children']:
            collect_and_encode(child, new_path)

    collect_and_encode(change_data, [])
    return features

def build_vocab_from_data(df, min_freq=1, max_paths=5000):
    """Build path-context vocabulary:
- Collect all (path_tuple, token) pairs
- Only retain items with frequency >= min_freq and top max_paths items
"""
    from collections import Counter
    
    path_token_pairs = []

    def collect_paths(node, current_path):
        new_path = current_path + [node['node_type']]
        if node['content'].strip():
            tokens = node['content'].strip().split()
            for tok in tokens:
                #Paths stored as tuples (hashable)
                path_token_pairs.append((tuple(new_path), tok))
        for child in node['children']:
            collect_paths(child, new_path)

    for change in df['change_data']:
        collect_paths(change, [])
    
    #Count frequency
    pair_counts = Counter(path_token_pairs)
    
    #Build vocabulary: retain only high-frequency items
    vocab = {}
    for (path, tok), cnt in pair_counts.most_common(max_paths):
        if cnt >= min_freq:
            vocab[(path, tok)] = len(vocab)  #Continuous index
    
    print(f"Built path-context vocab with {len(vocab)} entries.")
    return vocab  #Note: now vocab is {(path, token): idx}

def build_feature_matrix(df, type_vocab, token_vocab):
    """
    Build the complete feature vector for each sample:
    [Change Tree Encoding] + [Meta Features]
    """
    features = []
    
    for idx, row in df.iterrows():
        # 1. Change Tree Structure Encoding
        tree_vec = encode_change_tree(row['change_data'], type_vocab=type_vocab, token_vocab=token_vocab)

        # 2. Meta Features (Normalized)
        meta_features = np.array([
            np.log1p(row['change_lines']),
            row['change_ratio'],
            np.log1p(row['avg_change_lines_in_scope']),
            1 if row['change_type'] == 'insert' else 0,
            1 if row['change_type'] == 'delete' else 0,
            1 if row['change_type'] == 'update' else 0,
            1 if row['change_type'] == 'modify' else 0,  # Other types
            int(row['method_signature_changed']['method_name_or_params_changed']),
            int(row['method_signature_changed']['class_name_changed'])
        ])
        
        # Concatenate
        full_vec = np.concatenate([tree_vec, meta_features])
        features.append(full_vec)
    
    return np.array(features, dtype=np.float32)

class ChangeClassifier(nn.Module):
    def __init__(self, input_dim, hidden_dim=256, dropout=0.3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, 1)
        )
    
    def forward(self, x):
        return self.net(x).squeeze(-1)

class FocalLoss(nn.Module):
    def __init__(self, alpha=0.75, gamma=2.0, pos_weight=None):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.pos_weight = pos_weight  # Add New Parameters
        
    def forward(self, inputs, targets):
        BCE_loss = nn.BCEWithLogitsLoss(reduction='none')(inputs, targets)
        pt = torch.exp(-BCE_loss)
        
        # Base Focal Loss
        F_loss = self.alpha * (1-pt)**self.gamma * BCE_loss
        
        # If pos_weight is provided, further adjust positive sample weights
        if self.pos_weight is not None:
            # Increase additional weight for positive samples
            pos_mask = targets > 0.5
            F_loss[pos_mask] = F_loss[pos_mask] * self.pos_weight
        
        return F_loss.mean()


def train_model(X_train, y_train, X_val, y_val, device, epochs=50, batch_size=64):
    # Convert to Tensor
    X_train_t = torch.tensor(X_train, dtype=torch.float32).to(device)
    y_train_t = torch.tensor(y_train, dtype=torch.float32).to(device)
    X_val_t = torch.tensor(X_val, dtype=torch.float32).to(device)
    y_val_t = torch.tensor(y_val, dtype=torch.float32).to(device)
    
    # DataLoader
    train_loader = DataLoader(TensorDataset(X_train_t, y_train_t), 
                              batch_size=batch_size, shuffle=True)
    
    # Model & Optimizer
    model = ChangeClassifier(X_train.shape[1]).to(device)
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    
    # Class Weighting (Handle Imbalance)
    class_weights = compute_class_weight('balanced', classes=np.unique(y_train), y=y_train)
    pos_weight = torch.tensor(class_weights[1], dtype=torch.float32).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    #criterion = FocalLoss(alpha=0.75, gamma=2.0, pos_weight=pos_weight)
    
    #Training Loop
    best_f2, best_model_state = 0, None
    for epoch in range(epochs):
        model.train()
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            logits = model(X_batch)
            loss = criterion(logits, y_batch)
            loss.backward()
            optimizer.step()
        
        #Validation Set Evaluation
        model.eval()
        with torch.no_grad():
            val_logits = model(X_val_t)
            val_probs = torch.sigmoid(val_logits).cpu().numpy()
            
            #Find Best F2 with Multiple Thresholds
            best_f2_epoch = 0
            for thresh in np.arange(0.1, 0.6, 0.05):
                preds = (val_probs >= thresh).astype(int)
                f2 = fbeta_score(y_val, preds, beta=2, zero_division=0)
                if f2 > best_f2_epoch:
                    best_f2_epoch = f2
            
            if best_f2_epoch > best_f2:
                best_f2 = best_f2_epoch
                best_model_state = model.state_dict().copy()
        
        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1}: Val F2 = {best_f2_epoch:.4f}")
    
    model.load_state_dict(best_model_state)
    return model


def select_threshold(model, X_val, y_val, device):
    """Select the decision threshold using validation data only."""
    model.eval()
    X_val_t = torch.tensor(X_val, dtype=torch.float32).to(device)

    with torch.no_grad():
        logits = model(X_val_t)
        probs = torch.sigmoid(logits).cpu().numpy()

    #Prioritize Recall >= 0.8, Then Maximize F2
    results = []
    best_thresh, best_f2 = 0.5, 0
    for thresh in np.arange(0.05, 0.6, 0.01):
        preds = (probs >= thresh).astype(int)
        prec = precision_score(y_val, preds, zero_division=0)
        rec = recall_score(y_val, preds, zero_division=0)
        f2 = fbeta_score(y_val, preds, beta=2, zero_division=0)
        results.append((thresh, prec, rec, f2))
        if rec >= 0.80 and f2 > best_f2:
            best_f2 = f2
            best_thresh = thresh

    #If No Threshold Meets Recall Constraint, Choose Threshold with Highest Recall on Validation Set
    if best_f2 == 0:
        best_thresh = max(results, key=lambda x: x[2])[0]

    print(f"Selected threshold on validation students: {best_thresh:.2f}")
    return best_thresh


def evaluate_model(
    model,
    X_test,
    y_test,
    device,
    test_df_original,
    output_excel_path=None,
    threshold=None,
):
    model.eval()
    X_test_t = torch.tensor(X_test, dtype=torch.float32).to(device)
    y_test_t = torch.tensor(y_test, dtype=torch.float32).to(device)

    with torch.no_grad():
        logits = model(X_test_t)
        probs = torch.sigmoid(logits).cpu().numpy()

    #Compat with Old Call: If No Fixed Threshold Provided, Still Select Threshold on Input Data
    #Formal Training Process Will Pass Threshold Determined Only by Validation Student, Avoid Label Leakage from Evaluation Set
    if threshold is None:
        best_thresh, best_f2 = 0.5, 0
        results = []
        for thresh in np.arange(0.05, 0.6, 0.01):
            preds = (probs >= thresh).astype(int)
            prec = precision_score(y_test, preds, zero_division=0)
            rec = recall_score(y_test, preds, zero_division=0)
            f2 = fbeta_score(y_test, preds, beta=2, zero_division=0)
            results.append((thresh, prec, rec, f2))
            if rec >= 0.80 and f2 > best_f2:
                best_f2 = f2
                best_thresh = thresh
        if best_f2 == 0:
            best_thresh = max(results, key=lambda x: x[2])[0]
    else:
        best_thresh = float(threshold)
    
    #Final Prediction
    final_preds = (probs >= best_thresh).astype(int)
    
    print(f"\n=== Evaluation Results (Threshold = {best_thresh:.2f}) ===")
    print(f"Precision: {precision_score(y_test, final_preds):.4f}")
    print(f"Recall:    {recall_score(y_test, final_preds):.4f}")
    print(f"F1-score:  {f1_score(y_test, final_preds):.4f}")
    print(f"F2-score:  {fbeta_score(y_test, final_preds, beta=2, zero_division=0):.4f}")
    print(f"AUC:       {roc_auc_score(y_test, probs):.4f}")
    print("\nDetailed Report:")
    print(classification_report(y_test, final_preds, target_names=['Negative', 'Positive']))

    predicted_positive_indices = np.where(final_preds == 1)[0]

    if len(predicted_positive_indices) == 0:
        print("\nWarning: No samples predicted as positive. Excel file will not be created.")
        return best_thresh, final_preds, probs

    #Select These Rows from Original DataFrame
    predicted_positive_df = test_df_original.iloc[predicted_positive_indices].copy()

    #Extract Pre-Change and Post-Change Ranges (Merge Child Node Positions)
    old_positions = []
    new_positions = []
    for _, row in predicted_positive_df.iterrows():
        change_data = row['change_data'] #This is Parent Node Information of the Change Node
        children = change_data.get('children', [])

        if not children:
            #If No Child Nodes, Record as N/A
            old_positions.append("N/A")
            new_positions.append("N/A")
        else:
            # --- Core Change: Merge Child Node Positions ---
            # Collect old and new positions of all child nodes
            old_starts = [child.get('old_start', -1) for child in children]
            old_ends = [child.get('old_end', -1) for child in children]
            new_starts = [child.get('start_pos', -1) for child in children]
            new_ends = [child.get('end_pos', -1) for child in children]

            # Filter out -1 values, as they indicate absence in this version
            valid_old_starts = [s for s in old_starts if s != -1]
            valid_old_ends = [e for e in old_ends if e != -1]
            valid_new_starts = [s for s in new_starts if s != -1]
            valid_new_ends = [e for e in new_ends if e != -1]

            # Calculate merged range
            if valid_old_starts and valid_old_ends:
                min_old_start = min(valid_old_starts)
                max_old_end = max(valid_old_ends)
                old_pos_str = f"[{min_old_start}, {max_old_end}]"
            elif all(s == -1 for s in old_starts) and all(e == -1 for e in old_ends):
                 # All child nodes did not exist in the old version
                 old_pos_str = "[-1, -1]"
            else:
                 # Some positions exist while others do not; represent the missing range as [-1, -1].
                 # Handling mixed cases: if there are valid values, take the valid range; if all are -1, then [-1,-1]; if all are -1 but the list is not empty (theoretically, there should be no values other than -1), it might be N/A
                 # A more rigorous approach is to check if all are -1
                 if all(s == -1 for s in old_starts) and all(e == -1 for e in old_ends):
                     old_pos_str = "[-1, -1]"
                 elif valid_old_starts and valid_old_ends: # At least one valid value
                     min_old_start = min(valid_old_starts)
                     max_old_end = max(valid_old_ends)
                     old_pos_str = f"[{min_old_start}, {max_old_end}]"
                 else: # Theoretically should not reach here
                     old_pos_str = "N/A"

            if valid_new_starts and valid_new_ends:
                min_new_start = min(valid_new_starts)
                max_new_end = max(valid_new_ends)
                new_pos_str = f"[{min_new_start}, {max_new_end}]"
            elif all(s == -1 for s in new_starts) and all(e == -1 for e in new_ends):
                 # All child nodes do not exist in the new version (theoretically, delete type should not reach here since pred is 1)
                 new_pos_str = "[-1, -1]"
            else:
                 # Handling mixed cases
                 if all(s == -1 for s in new_starts) and all(e == -1 for e in new_ends):
                     new_pos_str = "[-1, -1]"
                 elif valid_new_starts and valid_new_ends: #At least one valid value
                     min_new_start = min(valid_new_starts)
                     max_new_end = max(valid_new_ends)
                     new_pos_str = f"[{min_new_start}, {max_new_end}]"
                 else: #Should not reach theoretically
                     new_pos_str = "N/A"


            old_positions.append(old_pos_str)
            new_positions.append(new_pos_str)

    #Add new column
    predicted_positive_df['old_position_merged'] = old_positions
    predicted_positive_df['new_position_merged'] = new_positions

    #Select needed columns
    output_columns = [
        'homework_id',      # Assignment ID
        'student_id',       # Student ID
        'file_path',        # File Path
        'old_position_merged', #Merge position before change
        'new_position_merged', #Merge position after change
        'label'             #Actual label
    ]

    #Ensure column exists
    missing_cols = [col for col in output_columns if col not in predicted_positive_df.columns]
    if missing_cols:
        print(f"Warning: Columns {missing_cols} not found in test_df_original. They will be added with NaN.")
        for col in missing_cols:
            predicted_positive_df[col] = np.nan

    output_df = predicted_positive_df[output_columns].copy()

    #Rename column for clarity
    output_df.rename(columns={
        'homework_id': 'Assignment ID',
        'student_id': 'Student ID',
        'file_path': 'File Path',
        'old_position_merged': 'Old Change Position',
        'new_position_merged': 'New Change Position',
        'label': 'Ground-truth Label'
    }, inplace=True)

    #Save to Excel
    if output_excel_path is not None:
        output_filename = str(_prepare_output(output_excel_path))
        output_df.to_excel(output_filename, index=False, engine='openpyxl')
        print(f"\nSaved {len(output_df)} predicted positive samples to '{output_filename}'.")

    # --- New added end ---

    return best_thresh, final_preds, probs

def use_trained_model(
    test_df_path=OUTPUT_DIR / "test_df_by_student.pkl",
    model_checkpoint_path=MODEL_DIR / "hiretest_classifier.pth",
    output_pkl_path=OUTPUT_DIR / "evaluation_results.pkl",
    positive_excel_path=OUTPUT_DIR / "positive_predictions.xlsx",
):
    #Load previously split test_df
    test_df = pd.read_pickle(test_df_path)
    y_test = test_df['label'].values

    #Load model and vocabulary
    checkpoint = torch.load(model_checkpoint_path, map_location='cpu', weights_only=False) 
    
    type_vocab = checkpoint['type_vocab']
    token_vocab = checkpoint['token_vocab']
    saved_threshold = checkpoint['threshold']

    #Build features (using the training vocab)
    X_test = build_feature_matrix(test_df, type_vocab, token_vocab)

    #Load model
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    input_dim = X_test.shape[1]
    model = ChangeClassifier(input_dim=input_dim)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.to(device)
    model.eval()

    #Evaluate
    best_thresh, preds, probs = evaluate_model(model, X_test, y_test, device, test_df, positive_excel_path)
    
    test_df['predicted_prob'] = probs
    test_df['predicted_label'] = preds
    test_df.to_pickle(_prepare_output(output_pkl_path))

def train_and_evaluate(
    pkl_file=WORKSPACE_ROOT / "processed_data.pkl",
    model_output_path=MODEL_DIR / "hiretest_classifier.pth",
    test_results_output_path=OUTPUT_DIR / "test_results.pkl",
    test_df_output_path=OUTPUT_DIR / "test_df_by_student.pkl",
    positive_excel_path=OUTPUT_DIR / "positive_predictions.xlsx",
):
    
    #Step 1: Split by student
    with open(pkl_file, 'rb') as f:
        data = pickle.load(f)
    df = pd.DataFrame(data)

    #Get all students, and split into mutually exclusive 20%/10%/70% groups.
    all_students = df['student_id'].unique().copy()

    np.random.seed(10)  #Ensure reproducibility
    np.random.shuffle(all_students)
    n_train_students = int(len(all_students) * 0.2)
    n_val_students = int(len(all_students) * 0.1)
    train_students = set(all_students[:n_train_students])
    val_students = set(all_students[n_train_students:n_train_students + n_val_students])
    history_source_students = set(all_students[n_train_students + n_val_students:])

    assert train_students.isdisjoint(val_students)
    assert train_students.isdisjoint(history_source_students)
    assert val_students.isdisjoint(history_source_students)
    assert train_students | val_students | history_source_students == set(all_students)

    #Split DataFrame by student
    train_df = df[df['student_id'].isin(train_students)].reset_index(drop=True)
    val_df = df[df['student_id'].isin(val_students)].reset_index(drop=True)
    history_source_df = df[df['student_id'].isin(history_source_students)].reset_index(drop=True)

    print(f"Train students: {len(train_students)}, samples: {len(train_df)}")
    print(f"Validation students: {len(val_students)}, samples: {len(val_df)}")
    print(f"History-source students: {len(history_source_students)}, samples: {len(history_source_df)}")

    #Step 2: Build path-context vocabulary (only using training set)
    path_context_vocab = build_vocab_from_data(train_df, min_freq=2, max_paths=5000)

    #Step 3: Build feature matrix
    #Note: token_vocab is set to None, because encode_change_tree now only uses path_context_vocab
    X_train = build_feature_matrix(train_df, type_vocab=path_context_vocab, token_vocab=None)
    y_train = train_df['label'].values

    # Step 4: Validation set comes from an independent 10% student group.
    X_val = build_feature_matrix(val_df, type_vocab=path_context_vocab, token_vocab=None)
    y_val = val_df['label'].values

    # Step 5: Train the model
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = train_model(X_train, y_train, X_val, y_val, device, epochs=50)

    # Step 6: Select threshold only on validation students; evaluate 70% history-source group with fixed threshold.
    best_thresh = select_threshold(model, X_val, y_val, device)
    X_history_source = build_feature_matrix(
        history_source_df, type_vocab=path_context_vocab, token_vocab=None
    )
    y_history_source = history_source_df['label'].values

    best_thresh, preds, probs = evaluate_model(
        model,
        X_history_source,
        y_history_source,
        device,
        history_source_df,
        positive_excel_path,
        threshold=best_thresh,
    )

    # Step 7: Save the model and results
    torch.save({
        'model_state_dict': model.state_dict(),
        'threshold': best_thresh,
        'type_vocab': path_context_vocab,  # Note: Now type_vocab is actually path_context_vocab
        'token_vocab': None  # No longer used
    }, _prepare_output(model_output_path))

    # Save complete results (with predictions) of 70% history-source group.
    history_source_df['predicted_prob'] = probs
    history_source_df['predicted_label'] = preds
    history_source_df.to_pickle(_prepare_output(test_results_output_path))

    # Keep existing output parameter names for compatibility with downstream code; content is 70% history-source group.
    history_source_df.to_pickle(_prepare_output(test_df_output_path))

    print("✅ Final evaluation completed on the 70% student history-source set.")


def predict_new_data(
    new_data_pkl=WORKSPACE_ROOT / "processed_new_data.pkl",
    model_path=MODEL_DIR / "hiretest_classifier.pth",
    output_pkl_path=OUTPUT_DIR / "new_data_predictions.pkl",
    output_excel_path=OUTPUT_DIR / "new_data_predictions.xlsx",
):
    """
    Use the trained model to make predictions on new data.
    """
    # 1. Load new data
    with open(new_data_pkl, 'rb') as f:
        new_data = pickle.load(f)
    new_df = pd.DataFrame(new_data)
    print(f"Loaded new data: {len(new_df)} samples.")

    # 2. Load trained model and vocabulary
    print(f"Loading model and vocabularies from {model_path}...")
    checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
    
    model_state_dict = checkpoint['model_state_dict']
    type_vocab = checkpoint['type_vocab']
    token_vocab = checkpoint['token_vocab']
    saved_threshold = checkpoint['threshold']
    print(f"Loaded model threshold: {saved_threshold:.2f}")

    # 3. Build feature vectors for new data (using loaded vocab)
    print("Building feature matrix for new data...")
    X_new = build_feature_matrix(new_df, type_vocab, token_vocab)
    #No 'label' column in new data
    y_new = new_df.get('label', np.full(len(new_df), -1))  #If no label, fill with -1

    #4. Initialize and load model
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")
    
    #Reinitialize model structure
    input_dim = X_new.shape[1]
    model = ChangeClassifier(input_dim=input_dim)
    model.load_state_dict(model_state_dict)
    model.to(device)
    model.eval()
    print("Model loaded successfully.")

    #5. Perform prediction
    print("Making predictions on new data...")
    X_new_t = torch.tensor(X_new, dtype=torch.float32).to(device)
    with torch.no_grad():
        logits = model(X_new_t)
        probs = torch.sigmoid(logits).cpu().numpy()
    
    #Use saved threshold for final prediction
    final_preds = (probs >= saved_threshold).astype(int)
    print(f"Prediction completed using saved threshold: {saved_threshold:.2f}")

    #6. Save full prediction results
    new_df['predicted_prob'] = probs
    new_df['predicted_label'] = final_preds
    new_df.to_pickle(_prepare_output(output_pkl_path))
    print(f"Full prediction results saved to {output_pkl_path}")

    #7. If positive samples are predicted, generate Excel report
    if final_preds.sum() > 0:
        print(f"Found {final_preds.sum()} predicted positive samples. Generating Excel report...")
        #--- Reuse core logic from evaluate_model to generate report ---
        predicted_positive_indices = np.where(final_preds == 1)[0]
        predicted_positive_df = new_df.iloc[predicted_positive_indices].copy()

        old_positions = []
        new_positions = []
        for _, row in predicted_positive_df.iterrows():
            change_data = row['change_data'] #This is the parent node information for change nodes
            children = change_data.get('children', [])

            if not children:
                #If no child nodes, record as N/A
                old_positions.append("N/A")
                new_positions.append("N/A")
            else:
                #--- Core change: Set default values for old_pos_str and new_pos_str ---
                old_pos_str = "N/A"  # <-- default value
                new_pos_str = "N/A"  # <-- default value

                # extract and merge child node positions
                old_starts = [child.get('old_start', -1) for child in children]
                old_ends = [child.get('old_end', -1) for child in children]
                new_starts = [child.get('start_pos', -1) for child in children] # Note: the new version position field name is 'start_pos'/'end_pos'
                new_ends = [child.get('end_pos', -1) for child in children]

                valid_old_starts = [s for s in old_starts if s != -1]
                valid_old_ends = [e for e in old_ends if e != -1]
                valid_new_starts = [s for s in new_starts if s != -1]
                valid_new_ends = [e for e in new_ends if e != -1]

                # process old version positions
                if valid_old_starts and valid_old_ends:
                    min_old_start = min(valid_old_starts)
                    max_old_end = max(valid_old_ends)
                    old_pos_str = f"[{min_old_start}, {max_old_end}]"
                elif all(s == -1 for s in old_starts) and all(e == -1 for e in old_ends):
                    old_pos_str = "[-1, -1]"
                # else: 
                #     # mixed case, retain default value "N/A"
                #     pass

                # process new version positions
                if valid_new_starts and valid_new_ends:
                    min_new_start = min(valid_new_starts)
                    max_new_end = max(valid_new_ends)
                    new_pos_str = f"[{min_new_start}, {max_new_end}]"
                elif all(s == -1 for s in new_starts) and all(e == -1 for e in new_ends):
                    new_pos_str = "[-1, -1]"
                # else: 
                #     # mixed case, retain default value "N/A"
                #     pass

                old_positions.append(old_pos_str)
                new_positions.append(new_pos_str)

        # prepare output DataFrame
        predicted_positive_df['old_position_merged'] = old_positions
        predicted_positive_df['new_position_merged'] = new_positions

        output_columns = [
            'homework_id', 'student_id', 'file_path',
            'old_position_merged', 'new_position_merged'
        ]
        # if new data has a 'label' column, include it as well
        if 'label' in predicted_positive_df.columns:
            output_columns.append('label')
        
        # handle missing columns
        missing_cols = [col for col in output_columns if col not in predicted_positive_df.columns]
        for col in missing_cols:
            predicted_positive_df[col] = "N/A"
        
        output_df = predicted_positive_df[output_columns].copy()
        output_df.rename(columns={
            'homework_id': 'Assignment ID',
            'student_id': 'Student ID',
            'file_path': 'File Path',
            'old_position_merged': 'Old Change Position',
            'new_position_merged': 'New Change Position',
            'label': 'Ground-truth Label'
        }, inplace=True)

        #Save Excel
        output_df.to_excel(_prepare_output(output_excel_path), index=False, engine='openpyxl')
        print(f"Positive samples report saved to {output_excel_path}.")

    else:
        print("No samples were predicted as positive.")


def parse_args():
    parser = argparse.ArgumentParser(description="Train/evaluate HiReTest bug-fix classifier.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="Train model from processed_data.pkl.")
    train_parser.add_argument("--processed-data", default=str(WORKSPACE_ROOT / "processed_data.pkl"))
    train_parser.add_argument("--model-output", default=str(MODEL_DIR / "hiretest_classifier.pth"))
    train_parser.add_argument("--test-results-output", default=str(OUTPUT_DIR / "test_results.pkl"))
    train_parser.add_argument("--test-df-output", default=str(OUTPUT_DIR / "test_df_by_student.pkl"))
    train_parser.add_argument("--positive-excel", default=str(OUTPUT_DIR / "positive_predictions.xlsx"))

    eval_parser = subparsers.add_parser("evaluate", help="Evaluate existing model and export positive predictions.")
    eval_parser.add_argument("--test-df", default=str(OUTPUT_DIR / "test_df_by_student.pkl"))
    eval_parser.add_argument("--model", default=str(MODEL_DIR / "hiretest_classifier.pth"))
    eval_parser.add_argument("--output-pkl", default=str(OUTPUT_DIR / "evaluation_results.pkl"))
    eval_parser.add_argument("--positive-excel", default=str(OUTPUT_DIR / "positive_predictions.xlsx"))

    predict_parser = subparsers.add_parser("predict-new", help="Predict on a separate processed data pickle.")
    predict_parser.add_argument("--new-data", default=str(WORKSPACE_ROOT / "processed_new_data.pkl"))
    predict_parser.add_argument("--model", default=str(MODEL_DIR / "hiretest_classifier.pth"))
    predict_parser.add_argument("--output-pkl", default=str(OUTPUT_DIR / "new_data_predictions.pkl"))
    predict_parser.add_argument("--output-excel", default=str(OUTPUT_DIR / "new_data_predictions.xlsx"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.command == "train":
        train_and_evaluate(
            pkl_file=args.processed_data,
            model_output_path=args.model_output,
            test_results_output_path=args.test_results_output,
            test_df_output_path=args.test_df_output,
            positive_excel_path=args.positive_excel,
        )
    elif args.command == "evaluate":
        use_trained_model(
            test_df_path=args.test_df,
            model_checkpoint_path=args.model,
            output_pkl_path=args.output_pkl,
            positive_excel_path=args.positive_excel,
        )
    elif args.command == "predict-new":
        predict_new_data(
            new_data_pkl=args.new_data,
            model_path=args.model,
            output_pkl_path=args.output_pkl,
            output_excel_path=args.output_excel,
        )
