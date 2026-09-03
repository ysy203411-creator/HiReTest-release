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

RELEASE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.environ.get("HIRETEST_DERIVED_DATA_ROOT", RELEASE_ROOT / "data" / "restricted"))

def load_by_student_split(pkl_path: str, train_ratio=0.3, random_state=42):
    """
    按学生 ID 划分：随机抽取 train_ratio 的学生作为训练集，其余为测试集。
    所有属于该学生的所有样本都进入对应集合。
    """
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
    
    df = pd.DataFrame(data)
    print(f"Total samples: {len(df)}, Students: {df['student_id'].nunique()}")
    print(f"Positive rate overall: {df['label'].mean():.1%}")

    # 获取所有唯一学生 ID
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
    使用 path-context 编码。
    注意：type_vocab 和 token_vocab 参数不再使用，但保留接口兼容性。
    实际使用的是 path_context_vocab（通过 type_vocab 传入，见下文说明）。
    """
    # 为了兼容你的调用方式，我们约定：
    #   type_vocab 实际上传入的是 path_context_vocab
    path_context_vocab = type_vocab  # 重命名以清晰

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
    """
    构建 path-context 词汇表：
    - 收集所有 (path_tuple, token) 对
    - 只保留频次 >= min_freq 且排名前 max_paths 的项
    """
    from collections import Counter
    
    path_token_pairs = []

    def collect_paths(node, current_path):
        new_path = current_path + [node['node_type']]
        if node['content'].strip():
            tokens = node['content'].strip().split()
            for tok in tokens:
                # 路径用 tuple 存储（可哈希）
                path_token_pairs.append((tuple(new_path), tok))
        for child in node['children']:
            collect_paths(child, new_path)

    for change in df['change_data']:
        collect_paths(change, [])
    
    # 统计频次
    pair_counts = Counter(path_token_pairs)
    
    # 构建词汇表：只保留高频项
    vocab = {}
    for (path, tok), cnt in pair_counts.most_common(max_paths):
        if cnt >= min_freq:
            vocab[(path, tok)] = len(vocab)  # 连续索引
    
    print(f"Built path-context vocab with {len(vocab)} entries.")
    return vocab  # 注意：现在 vocab 是 {(path, token): idx}

def build_feature_matrix(df, type_vocab, token_vocab):
    """
    构建每条样本的完整特征向量：
    [变更树编码] + [元特征]
    """
    features = []
    
    for idx, row in df.iterrows():
        # 1. 变更树结构编码
        tree_vec = encode_change_tree(row['change_data'], type_vocab=type_vocab, token_vocab=token_vocab)

        # 2. 元特征（归一化）
        meta_features = np.array([
            np.log1p(row['change_lines']),
            row['change_ratio'],
            np.log1p(row['avg_change_lines_in_scope']),
            1 if row['change_type'] == 'insert' else 0,
            1 if row['change_type'] == 'delete' else 0,
            1 if row['change_type'] == 'update' else 0,
            1 if row['change_type'] == '修改' else 0,  # 其他类型
            int(row['method_signature_changed']['method_name_or_params_changed']),
            int(row['method_signature_changed']['class_name_changed'])
        ])
        
        # 拼接
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
        self.pos_weight = pos_weight  # 新增参数
        
    def forward(self, inputs, targets):
        BCE_loss = nn.BCEWithLogitsLoss(reduction='none')(inputs, targets)
        pt = torch.exp(-BCE_loss)
        
        # 基础Focal Loss
        F_loss = self.alpha * (1-pt)**self.gamma * BCE_loss
        
        # 如果提供了pos_weight，进一步调整正样本权重
        if self.pos_weight is not None:
            # 为正样本增加额外权重
            pos_mask = targets > 0.5
            F_loss[pos_mask] = F_loss[pos_mask] * self.pos_weight
        
        return F_loss.mean()


def train_model(X_train, y_train, X_val, y_val, device, epochs=50, batch_size=64):
    # 转为 Tensor
    X_train_t = torch.tensor(X_train, dtype=torch.float32).to(device)
    y_train_t = torch.tensor(y_train, dtype=torch.float32).to(device)
    X_val_t = torch.tensor(X_val, dtype=torch.float32).to(device)
    y_val_t = torch.tensor(y_val, dtype=torch.float32).to(device)
    
    # DataLoader
    train_loader = DataLoader(TensorDataset(X_train_t, y_train_t), 
                              batch_size=batch_size, shuffle=True)
    
    # 模型 & 优化器
    model = ChangeClassifier(X_train.shape[1]).to(device)
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    
    # 类别权重（处理不平衡）
    class_weights = compute_class_weight('balanced', classes=np.unique(y_train), y=y_train)
    pos_weight = torch.tensor(class_weights[1], dtype=torch.float32).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    #criterion = FocalLoss(alpha=0.75, gamma=2.0, pos_weight=pos_weight)
    
    # 训练循环
    best_f2, best_model_state = 0, None
    for epoch in range(epochs):
        model.train()
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            logits = model(X_batch)
            loss = criterion(logits, y_batch)
            loss.backward()
            optimizer.step()
        
        # 验证集评估
        model.eval()
        with torch.no_grad():
            val_logits = model(X_val_t)
            val_probs = torch.sigmoid(val_logits).cpu().numpy()
            
            # 用多个阈值找最佳F2
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

    # 优先保证 Recall >= 0.8，再最大化 F2。
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

    # 若没有满足 Recall 约束的阈值，则选择验证集上 Recall 最高的阈值。
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

    # 兼容旧调用：未提供固定阈值时，仍在传入数据上选择阈值。
    # 正式训练流程会传入仅由验证学生确定的阈值，避免评估集标签泄漏。
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
    
    # 最终预测
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

    # 从原始 DataFrame 中选取这些行
    predicted_positive_df = test_df_original.iloc[predicted_positive_indices].copy()

    # 提取变更前和变更后的范围（合并子节点位置）
    old_positions = []
    new_positions = []
    for _, row in predicted_positive_df.iterrows():
        change_data = row['change_data'] # 这是变更节点的父节点信息
        children = change_data.get('children', [])

        if not children:
            # 如果没有子节点，则记录为 N/A
            old_positions.append("N/A")
            new_positions.append("N/A")
        else:
            # --- 核心修改：合并子节点位置 ---
            # 收集所有子节点的旧/新位置
            old_starts = [child.get('old_start', -1) for child in children]
            old_ends = [child.get('old_end', -1) for child in children]
            new_starts = [child.get('start_pos', -1) for child in children]
            new_ends = [child.get('end_pos', -1) for child in children]

            # 过滤掉 -1 的值，因为它们表示该版本中不存在
            valid_old_starts = [s for s in old_starts if s != -1]
            valid_old_ends = [e for e in old_ends if e != -1]
            valid_new_starts = [s for s in new_starts if s != -1]
            valid_new_ends = [e for e in new_ends if e != -1]

            # 计算合并范围
            if valid_old_starts and valid_old_ends:
                min_old_start = min(valid_old_starts)
                max_old_end = max(valid_old_ends)
                old_pos_str = f"[{min_old_start}, {max_old_end}]"
            elif all(s == -1 for s in old_starts) and all(e == -1 for e in old_ends):
                 # 所有子节点在旧版本都不存在
                 old_pos_str = "[-1, -1]"
            else:
                 # 部分存在，部分不存在，按规则应为 N/A ?  还是取存在的范围？根据你的描述，-1,-1 应该写 [-1,-1]
                 # 这里处理混合情况：如果存在有效值，则取有效值范围；如果全为 -1，则 [-1,-1]；如果全为 -1 但列表不为空（理论上不应有 -1 之外的值），则可能是 N/A
                 # 更严谨的处理是只看是否全为 -1
                 if all(s == -1 for s in old_starts) and all(e == -1 for e in old_ends):
                     old_pos_str = "[-1, -1]"
                 elif valid_old_starts and valid_old_ends: # 至少有一个有效值
                     min_old_start = min(valid_old_starts)
                     max_old_end = max(valid_old_ends)
                     old_pos_str = f"[{min_old_start}, {max_old_end}]"
                 else: # 理论上不应到达
                     old_pos_str = "N/A"

            if valid_new_starts and valid_new_ends:
                min_new_start = min(valid_new_starts)
                max_new_end = max(valid_new_ends)
                new_pos_str = f"[{min_new_start}, {max_new_end}]"
            elif all(s == -1 for s in new_starts) and all(e == -1 for e in new_ends):
                 # 所有子节点在新版本都不存在 (理论上 delete 类型不会走到这里，因为 pred 为 1)
                 new_pos_str = "[-1, -1]"
            else:
                 # 处理混合情况
                 if all(s == -1 for s in new_starts) and all(e == -1 for e in new_ends):
                     new_pos_str = "[-1, -1]"
                 elif valid_new_starts and valid_new_ends: # 至少有一个有效值
                     min_new_start = min(valid_new_starts)
                     max_new_end = max(valid_new_ends)
                     new_pos_str = f"[{min_new_start}, {max_new_end}]"
                 else: # 理论上不应到达
                     new_pos_str = "N/A"


            old_positions.append(old_pos_str)
            new_positions.append(new_pos_str)

    # 添加新列
    predicted_positive_df['old_position_merged'] = old_positions
    predicted_positive_df['new_position_merged'] = new_positions

    # 选择需要的列
    output_columns = [
        'homework_id',      # 课程id
        'student_id',       # 学生id
        'file_path',        # 文件路径
        'old_position_merged', # 变更前合并位置
        'new_position_merged', # 变更后合并位置
        'label'             # 实际标签
    ]

    # 确保列存在
    missing_cols = [col for col in output_columns if col not in predicted_positive_df.columns]
    if missing_cols:
        print(f"Warning: Columns {missing_cols} not found in test_df_original. They will be added with NaN.")
        for col in missing_cols:
            predicted_positive_df[col] = np.nan

    output_df = predicted_positive_df[output_columns].copy()

    # 重命名列以便理解
    output_df.rename(columns={
        'homework_id': '课程id',
        'student_id': '学生id',
        'file_path': '文件路径',
        'old_position_merged': '代码变更修改前的位置',
        'new_position_merged': '代码变更修改后的位置',
        'label': '变更实际是否是正样本'
    }, inplace=True)

    # 保存到 Excel
    if output_excel_path is not None:
        output_filename = str(output_excel_path)
        output_df.to_excel(output_filename, index=False, engine='openpyxl')
        print(f"\nSaved {len(output_df)} predicted positive samples to '{output_filename}'.")

    # --- 新增结束 ---

    return best_thresh, final_preds, probs

def use_trained_model(
    test_df_path=PROJECT_ROOT / "test_df_by_student.pkl",
    model_checkpoint_path=PROJECT_ROOT / "final_model.pth",
    output_pkl_path=PROJECT_ROOT / "re_evaluated_test.pkl",
    positive_excel_path=PROJECT_ROOT / "positive_predictions1.xlsx",
):
    # 直接加载之前划分好的 test_df
    test_df = pd.read_pickle(test_df_path)
    y_test = test_df['label'].values

    # 加载模型和词表
    checkpoint = torch.load(model_checkpoint_path, map_location='cpu', weights_only=False) 
    
    type_vocab = checkpoint['type_vocab']
    token_vocab = checkpoint['token_vocab']
    saved_threshold = checkpoint['threshold']

    # 构建特征（使用训练时的 vocab）
    X_test = build_feature_matrix(test_df, type_vocab, token_vocab)

    # 加载模型
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    input_dim = X_test.shape[1]
    model = ChangeClassifier(input_dim=input_dim)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.to(device)
    model.eval()

    # 评估
    best_thresh, preds, probs = evaluate_model(model, X_test, y_test, device, test_df, positive_excel_path)
    
    test_df['predicted_prob'] = probs
    test_df['predicted_label'] = preds
    test_df.to_pickle(output_pkl_path)

def train_and_evaluate(
    pkl_file=PROJECT_ROOT / "processed_data.pkl",
    model_output_path=PROJECT_ROOT / "final_model_0419.pth",
    test_results_output_path=PROJECT_ROOT / "test_results_full.pkl",
    test_df_output_path=PROJECT_ROOT / "test_df_by_student.pkl",
    positive_excel_path=PROJECT_ROOT / "positive_predictions1.xlsx",
):
    
    # Step 1: 按学生划分
    with open(pkl_file, 'rb') as f:
        data = pickle.load(f)
    df = pd.DataFrame(data)

    # 获取全体学生，并按学生身份划分为互斥的 20%/10%/70% 三组。
    all_students = df['student_id'].unique().copy()

    np.random.seed(10)  # 保持可复现性
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

    # 按学生划分 DataFrame
    train_df = df[df['student_id'].isin(train_students)].reset_index(drop=True)
    val_df = df[df['student_id'].isin(val_students)].reset_index(drop=True)
    history_source_df = df[df['student_id'].isin(history_source_students)].reset_index(drop=True)

    print(f"Train students: {len(train_students)}, samples: {len(train_df)}")
    print(f"Validation students: {len(val_students)}, samples: {len(val_df)}")
    print(f"History-source students: {len(history_source_students)}, samples: {len(history_source_df)}")

    # Step 2: 构建 path-context 词汇表（仅用训练集）
    path_context_vocab = build_vocab_from_data(train_df, min_freq=2, max_paths=5000)

    # Step 3: 构建特征矩阵
    # 注意：token_vocab 设为 None，因为 encode_change_tree 现在只用 path_context_vocab
    X_train = build_feature_matrix(train_df, type_vocab=path_context_vocab, token_vocab=None)
    y_train = train_df['label'].values

    # Step 4: 验证集来自独立的 10% 学生组。
    X_val = build_feature_matrix(val_df, type_vocab=path_context_vocab, token_vocab=None)
    y_val = val_df['label'].values

    # Step 5: 训练模型
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = train_model(X_train, y_train, X_val, y_val, device, epochs=50)

    # Step 6: 仅在验证学生上选择阈值；使用固定阈值评估 70% history-source 组。
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

    # Step 7: 保存模型和结果
    torch.save({
        'model_state_dict': model.state_dict(),
        'threshold': best_thresh,
        'type_vocab': path_context_vocab,  # 注意：现在 type_vocab 实际是 path_context_vocab
        'token_vocab': None  # 不再使用
    }, model_output_path)

    # 保存 70% history-source 组的完整结果（含预测）。
    history_source_df['predicted_prob'] = probs
    history_source_df['predicted_label'] = preds
    history_source_df.to_pickle(test_results_output_path)

    # 保留既有输出参数名以兼容下游代码；内容为 70% history-source 组。
    history_source_df.to_pickle(test_df_output_path)

    print("✅ Final evaluation completed on the 70% student history-source set.")


def predict_new_data(
    new_data_pkl=PROJECT_ROOT / "data_2025" / "processed_data_2025.pkl",
    model_path=PROJECT_ROOT / "final_model.pth",
    output_pkl_path=PROJECT_ROOT / "new_data_predictions.pkl",
    output_excel_path=PROJECT_ROOT / "data_predictions_2025.xlsx",
):
    """
    使用已训练好的模型对新数据进行预测。
    """
    # 1. 加载新的数据
    with open(new_data_pkl, 'rb') as f:
        new_data = pickle.load(f)
    new_df = pd.DataFrame(new_data)
    print(f"Loaded new data: {len(new_df)} samples.")

    # 2. 加载已训练好的模型和词表
    print(f"Loading model and vocabularies from {model_path}...")
    checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
    
    model_state_dict = checkpoint['model_state_dict']
    type_vocab = checkpoint['type_vocab']
    token_vocab = checkpoint['token_vocab']
    saved_threshold = checkpoint['threshold']
    print(f"Loaded model threshold: {saved_threshold:.2f}")

    # 3. 构建新数据的特征向量 (使用加载的 vocab)
    print("Building feature matrix for new data...")
    X_new = build_feature_matrix(new_df, type_vocab, token_vocab)
    # 新数据没有'label' 列
    y_new = new_df.get('label', np.full(len(new_df), -1))  # 如果无label，则用-1填充

    # 4. 初始化并加载模型
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")
    
    # 重新初始化模型结构
    input_dim = X_new.shape[1]
    model = ChangeClassifier(input_dim=input_dim)
    model.load_state_dict(model_state_dict)
    model.to(device)
    model.eval()
    print("Model loaded successfully.")

    # 5. 进行预测
    print("Making predictions on new data...")
    X_new_t = torch.tensor(X_new, dtype=torch.float32).to(device)
    with torch.no_grad():
        logits = model(X_new_t)
        probs = torch.sigmoid(logits).cpu().numpy()
    
    # 使用保存的阈值进行最终预测
    final_preds = (probs >= saved_threshold).astype(int)
    print(f"Prediction completed using saved threshold: {saved_threshold:.2f}")

    # 6. 保存完整预测结果
    new_df['predicted_prob'] = probs
    new_df['predicted_label'] = final_preds
    new_df.to_pickle(output_pkl_path)
    print(f"Full prediction results saved to {output_pkl_path}")

    # 7. 如果存在正样本预测，生成Excel报告
    if final_preds.sum() > 0:
        print(f"Found {final_preds.sum()} predicted positive samples. Generating Excel report...")
        # --- 复用 evaluate_model 中的核心逻辑来生成报告 ---
        predicted_positive_indices = np.where(final_preds == 1)[0]
        predicted_positive_df = new_df.iloc[predicted_positive_indices].copy()

        old_positions = []
        new_positions = []
        for _, row in predicted_positive_df.iterrows():
            change_data = row['change_data'] # 这是变更节点的父节点信息
            children = change_data.get('children', [])

            if not children:
                # 如果没有子节点，则记录为 N/A
                old_positions.append("N/A")
                new_positions.append("N/A")
            else:
                # --- 核心修改：为 old_pos_str 和 new_pos_str 设置默认值 ---
                old_pos_str = "N/A"  # <-- 默认值
                new_pos_str = "N/A"  # <-- 默认值

                # 提取并合并子节点位置
                old_starts = [child.get('old_start', -1) for child in children]
                old_ends = [child.get('old_end', -1) for child in children]
                new_starts = [child.get('start_pos', -1) for child in children] # 注意：新版本位置字段名是'start_pos'/'end_pos'
                new_ends = [child.get('end_pos', -1) for child in children]

                valid_old_starts = [s for s in old_starts if s != -1]
                valid_old_ends = [e for e in old_ends if e != -1]
                valid_new_starts = [s for s in new_starts if s != -1]
                valid_new_ends = [e for e in new_ends if e != -1]

                # 处理旧版本位置
                if valid_old_starts and valid_old_ends:
                    min_old_start = min(valid_old_starts)
                    max_old_end = max(valid_old_ends)
                    old_pos_str = f"[{min_old_start}, {max_old_end}]"
                elif all(s == -1 for s in old_starts) and all(e == -1 for e in old_ends):
                    old_pos_str = "[-1, -1]"
                # else: 
                #     # 混合情况，保留默认值 "N/A"
                #     pass

                # 处理新版本位置
                if valid_new_starts and valid_new_ends:
                    min_new_start = min(valid_new_starts)
                    max_new_end = max(valid_new_ends)
                    new_pos_str = f"[{min_new_start}, {max_new_end}]"
                elif all(s == -1 for s in new_starts) and all(e == -1 for e in new_ends):
                    new_pos_str = "[-1, -1]"
                # else: 
                #     # 混合情况，保留默认值 "N/A"
                #     pass

                old_positions.append(old_pos_str)
                new_positions.append(new_pos_str)

        # 准备输出DataFrame
        predicted_positive_df['old_position_merged'] = old_positions
        predicted_positive_df['new_position_merged'] = new_positions

        output_columns = [
            'homework_id', 'student_id', 'file_path',
            'old_position_merged', 'new_position_merged'
        ]
        # 如果新数据里有 'label' 列，则也包含它
        if 'label' in predicted_positive_df.columns:
            output_columns.append('label')
        
        # 处理缺失列
        missing_cols = [col for col in output_columns if col not in predicted_positive_df.columns]
        for col in missing_cols:
            predicted_positive_df[col] = "N/A"
        
        output_df = predicted_positive_df[output_columns].copy()
        output_df.rename(columns={
            'homework_id': '课程id',
            'student_id': '学生id',
            'file_path': '文件路径',
            'old_position_merged': '代码变更修改前的位置',
            'new_position_merged': '代码变更修改后的位置',
            'label': '变更实际是否是正样本'
        }, inplace=True)

        # 保存Excel
        output_df.to_excel(output_excel_path, index=False, engine='openpyxl')
        print(f"Positive samples report saved to {output_excel_path}.")

    else:
        print("No samples were predicted as positive.")


def parse_args():
    parser = argparse.ArgumentParser(description="Train/evaluate HiReTest bug-fix classifier.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="Train model from processed_data.pkl.")
    train_parser.add_argument("--processed-data", default=str(PROJECT_ROOT / "processed_data.pkl"))
    train_parser.add_argument("--model-output", default=str(PROJECT_ROOT / "final_model_0419.pth"))
    train_parser.add_argument("--test-results-output", default=str(PROJECT_ROOT / "test_results_full.pkl"))
    train_parser.add_argument("--test-df-output", default=str(PROJECT_ROOT / "test_df_by_student.pkl"))
    train_parser.add_argument("--positive-excel", default=str(PROJECT_ROOT / "positive_predictions1.xlsx"))

    eval_parser = subparsers.add_parser("evaluate", help="Evaluate existing model and export positive predictions.")
    eval_parser.add_argument("--test-df", default=str(PROJECT_ROOT / "test_df_by_student.pkl"))
    eval_parser.add_argument("--model", default=str(PROJECT_ROOT / "final_model.pth"))
    eval_parser.add_argument("--output-pkl", default=str(PROJECT_ROOT / "re_evaluated_test.pkl"))
    eval_parser.add_argument("--positive-excel", default=str(PROJECT_ROOT / "positive_predictions1.xlsx"))

    predict_parser = subparsers.add_parser("predict-new", help="Predict on a separate processed data pickle.")
    predict_parser.add_argument("--new-data", default=str(PROJECT_ROOT / "data_2025" / "processed_data_2025.pkl"))
    predict_parser.add_argument("--model", default=str(PROJECT_ROOT / "final_model.pth"))
    predict_parser.add_argument("--output-pkl", default=str(PROJECT_ROOT / "new_data_predictions.pkl"))
    predict_parser.add_argument("--output-excel", default=str(PROJECT_ROOT / "data_predictions_2025.xlsx"))
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
